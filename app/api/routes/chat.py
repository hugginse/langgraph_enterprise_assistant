"""问答 SSE（POST /api/chat/ask）与会话/消息/历史接口。

SSE 事件序（进 SSE 前完成全部权限校验，失败为 JSON 401/403/404/409）：
  node(可选) → sources → thinking×N → delta×N → done / error
真流式：图在工作线程执行，on_token 逐块入队，消费侧即时下发；禁止整段切片。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import login_required
from app.db import SessionLocal, get_db
from app.models import (
    ChatMessage,
    ChatSession,
    EmbedIndexMeta,
    KbMember,
    KnowledgeBase,
    User,
)
from app.schemas.chat import (
    AskRequest,
    HistoryPage,
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from app.services import checkpoint as ckpt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

_HISTORY_LIMIT = 6  # 近 3 轮


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _require_kb_for_ask(db: Session, user: User, kb_id: int) -> KnowledgeBase:
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if user.role != "admin":
        member = db.scalar(
            select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user.id)
        )
        if member is None:
            raise HTTPException(status_code=403, detail="无权访问该知识库")
    return kb


def _check_fingerprint(db: Session, kb_id: int) -> None:
    """进 SSE 前校验 embed 指纹；不匹配 409（禁止静默用错向量）。"""
    meta = db.get(EmbedIndexMeta, kb_id)
    if meta is None:
        return
    from app.services.llm import create_embedder
    from app.services.vector import EmbeddingMismatchError, verify_fingerprint

    try:
        embedder = create_embedder()
    except Exception as exc:  # noqa: BLE001  缺 key 等显式失败
        raise HTTPException(status_code=500, detail=f"Embedding 通道不可用: {exc}") from exc
    try:
        verify_fingerprint(meta.embed_fingerprint, embedder.fingerprint)
    except EmbeddingMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _ensure_session(db: Session, user: User, body: AskRequest) -> ChatSession:
    if body.session_id is not None:
        session = db.get(ChatSession, body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.user_id != user.id and user.role != "admin":
            raise HTTPException(status_code=403, detail="无权访问该会话")
        if session.kb_id is not None and session.kb_id != body.kb_id:
            raise HTTPException(status_code=400, detail="会话与知识库不匹配")
        return session
    session = ChatSession(user_id=user.id, kb_id=body.kb_id, title="")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _assemble_history(db: Session, session_id: int) -> list[dict]:
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(_HISTORY_LIMIT)
    ).all()
    return [{"question": m.question, "answer": m.answer} for m in reversed(rows)]


def _persist_message(
    *, session_id: int, user_id: int, kb_id: int, question: str, final: dict
) -> tuple[int, str, float | None]:
    answer = final.get("answer") or ""
    status_v = final.get("status") or "answered"
    confidence = final.get("confidence")
    citations = final.get("citations") or []
    pdb = SessionLocal()
    try:
        msg = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            kb_id=kb_id,
            question=question,
            answer=answer,
            sources=citations,
            confidence=confidence,
            status=status_v,
        )
        pdb.add(msg)
        sess = pdb.get(ChatSession, session_id)
        if sess is not None and not sess.title:
            sess.title = question[:20]
        pdb.commit()
        pdb.refresh(msg)
        return msg.id, status_v, confidence
    finally:
        pdb.close()


@router.post("/ask")
def ask(
    body: AskRequest,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    # ---- 进 SSE 前：权限与配置校验（JSON 失败，不进流）----
    _require_kb_for_ask(db, user, body.kb_id)
    _check_fingerprint(db, body.kb_id)
    session = _ensure_session(db, user, body)
    history = _assemble_history(db, session.id)
    thread_id = str(session.id)

    from app.services.rag_runtime import get_graph

    graph = get_graph()

    initial_state: dict[str, Any] = {
        "question": body.question,
        "kb_id": body.kb_id,
        "history": history,
        "max_rewrite_attempts": settings.max_rewrite_attempts,
        "rewrite_count": 0,
        "retrieval_attempts": 0,
        "errors": [],
    }
    user_id = user.id
    session_id = session.id
    question = body.question
    kb_id = body.kb_id

    def event_stream() -> Iterator[str]:
        q: queue.Queue = queue.Queue()
        state: dict[str, Any] = {"chunks": [], "sources_sent": False}

        def on_token(kind: str, text: str) -> None:
            q.put((kind, {"text": text}))

        def on_node(name: str) -> None:
            if settings.enable_node_sse:
                q.put(("node", {"node": name}))

        def run() -> None:
            final: dict[str, Any] = {}
            try:
                config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "on_token": on_token,
                        "on_node": on_node,
                    }
                }
                for step in graph.stream(initial_state, config=config):
                    q.put(("__step__", step))
                    for _node, upd in step.items():
                        if isinstance(upd, dict):
                            final.update(upd)
                msg_id, status_v, confidence = _persist_message(
                    session_id=session_id,
                    user_id=user_id,
                    kb_id=kb_id,
                    question=question,
                    final=final,
                )
                q.put(
                    (
                        "done",
                        {
                            "session_id": session_id,
                            "message_id": msg_id,
                            "status": status_v,
                            "confidence": confidence,
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001  进图后故障 → SSE error
                logger.exception("chat/ask 图执行失败")
                q.put(("error", {"message": str(exc)}))
            finally:
                q.put(("__end__", None))

        def sources_payload(chunks: list[dict]) -> list[dict]:
            return [
                {
                    "file_name": c.get("file_name", ""),
                    "chunk_index": c.get("chunk_index", 0),
                    "score": float(c.get("score", 0.0)),
                    "snippet": (c.get("text") or "")[:200],
                }
                for c in chunks
            ]

        threading.Thread(target=run, daemon=True).start()

        while True:
            kind, payload = q.get()
            if kind == "__step__":
                if "retrieve" in payload and isinstance(payload["retrieve"], dict):
                    state["chunks"] = list(payload["retrieve"].get("chunks") or [])
                if "grade" in payload and not state["sources_sent"]:
                    state["sources_sent"] = True
                    yield _sse(
                        "sources", {"sources": sources_payload(state["chunks"])}
                    )
                continue
            if kind == "__end__":
                break
            if kind == "done":
                # 未经过 grade（如 clarification）→ 零命中 sources 兜底，先于 done
                if not state["sources_sent"]:
                    state["sources_sent"] = True
                    yield _sse("sources", {"sources": []})
                yield _sse("done", payload)
                continue
            # thinking / delta / node / error
            yield _sse(kind, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 会话 ----------


def _get_session_or_403(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return session


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
    user_id: int | None = Query(default=None),
) -> list[SessionOut]:
    q = select(ChatSession)
    if user.role == "admin":
        if user_id is not None:
            q = q.where(ChatSession.user_id == user_id)
    else:
        q = q.where(ChatSession.user_id == user.id)
    rows = db.scalars(q.order_by(ChatSession.id.desc())).all()
    return [SessionOut.model_validate(s) for s in rows]


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> SessionOut:
    if body.kb_id is not None:
        _require_kb_for_ask(db, user, body.kb_id)
    session = ChatSession(user_id=user.id, kb_id=body.kb_id, title=body.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionOut.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def rename_session(
    session_id: int,
    body: SessionUpdate,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> SessionOut:
    session = _get_session_or_403(db, user, session_id)
    session.title = body.title
    db.commit()
    db.refresh(session)
    return SessionOut.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> Response:
    session = _get_session_or_403(db, user, session_id)
    # 同步清 checkpoint（thread_id = str(session.id)）
    ckpt.delete_thread(str(session.id))
    db.delete(session)  # messages 由外键级联
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def session_messages(
    session_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    _get_session_or_403(db, user, session_id)
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
    ).all()
    return [MessageOut.model_validate(m) for m in rows]


# ---------- 历史 ----------


@router.get("/history", response_model=HistoryPage)
def chat_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int | None = Query(default=None),
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> HistoryPage:
    q = select(ChatMessage)
    if user.role == "admin":
        if user_id is not None:
            q = q.where(ChatMessage.user_id == user_id)
    else:
        q = q.where(ChatMessage.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(ChatMessage.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return HistoryPage(
        items=[MessageOut.model_validate(m) for m in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
