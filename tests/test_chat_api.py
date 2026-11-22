"""反馈、reindex、会话级联、检索调试单测（M3 feature 7）。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from app.services import checkpoint as ckpt
from app.services import rag_runtime
from app.services.adaptive_rag import build_graph
from tests.conftest import (
    ScriptedChatModel,
    add_member,
    auth_header,
    make_kb,
    make_user,
)


def _setup(client, db):
    admin = make_user(db, "root", role="admin")
    user = make_user(db, "alice")
    kb = make_kb(db, "库A", created_by=admin.id)
    add_member(db, kb.id, user.id)
    return admin, user, kb


def _make_message(db, user, kb, question="q", answer="a"):
    from app.models import ChatMessage, ChatSession

    session = ChatSession(user_id=user.id, kb_id=kb.id, title="t")
    db.add(session)
    db.commit()
    db.refresh(session)
    msg = ChatMessage(
        session_id=session.id,
        user_id=user.id,
        kb_id=kb.id,
        question=question,
        answer=answer,
        sources=[],
        confidence=0.5,
        status="answered",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return session, msg


# ---------- 反馈 ----------


def test_feedback_submit_and_upsert(client, db):
    _admin, alice, kb = _setup(client, db)
    _s, msg = _make_message(db, alice, kb)

    resp = client.post(
        "/api/chat/feedback",
        json={"message_id": msg.id, "score": 1, "comment": "有用"},
        headers=auth_header(alice),
    )
    assert resp.status_code == 200
    fb1 = resp.json()
    assert fb1["score"] == 1

    # 同用户同消息二次提交 → upsert 同一行
    resp2 = client.post(
        "/api/chat/feedback",
        json={"message_id": msg.id, "score": -1, "comment": "改了"},
        headers=auth_header(alice),
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == fb1["id"]
    assert resp2.json()["score"] == -1

    from sqlalchemy import func, select

    from app.models import ChatFeedback

    count = db.scalar(select(func.count()).select_from(ChatFeedback))
    assert count == 1


def test_feedback_rejects_invalid_score(client, db):
    _admin, alice, kb = _setup(client, db)
    _s, msg = _make_message(db, alice, kb)
    resp = client.post(
        "/api/chat/feedback",
        json={"message_id": msg.id, "score": 5},
        headers=auth_header(alice),
    )
    assert resp.status_code == 422


def test_feedback_unknown_message_404(client, db):
    _admin, alice, _kb = _setup(client, db)
    resp = client.post(
        "/api/chat/feedback",
        json={"message_id": 99999, "score": 1},
        headers=auth_header(alice),
    )
    assert resp.status_code == 404


def test_feedback_other_users_message_403(client, db):
    admin, alice, kb = _setup(client, db)
    _s, msg = _make_message(db, alice, kb)
    resp = client.post(
        "/api/chat/feedback",
        json={"message_id": msg.id, "score": 1},
        headers=auth_header(admin),
    )
    # admin 允许
    assert resp.status_code == 200
    bob = make_user(db, "bob")
    resp = client.post(
        "/api/chat/feedback",
        json={"message_id": msg.id, "score": 1},
        headers=auth_header(bob),
    )
    assert resp.status_code == 403


# ---------- reindex ----------


def test_reindex_admin_only_and_queued(client, db, monkeypatch):
    admin, alice, kb = _setup(client, db)
    called: list[int] = []

    import app.services.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "reindex_kb", lambda kid: called.append(kid))

    resp = client.post(
        f"/api/knowledge-bases/{kb.id}/reindex", headers=auth_header(alice)
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/knowledge-bases/{kb.id}/reindex", headers=auth_header(admin)
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "kb_id": kb.id}
    assert called == [kb.id]


# ---------- 会话级联 ----------


def test_session_delete_cascades_messages_and_checkpoint(client, db, monkeypatch):
    """删除会话：messages 级联 + 对应 thread checkpoint 清理。"""
    _admin, alice, kb = _setup(client, db)
    session, msg = _make_message(db, alice, kb)

    # 注入 InMemorySaver 并为该 thread 写入状态
    saver = InMemorySaver()
    monkeypatch.setattr(ckpt, "_SAVER", saver)
    monkeypatch.setattr(ckpt, "_SAVER_KIND", "memory")
    monkeypatch.setattr(ckpt.settings, "checkpoint_enabled", True, raising=False)

    rag_runtime.set_graph(
        build_graph(
            chat_model=ScriptedChatModel(chunks=[("delta", "回答")]),
            retriever=lambda q, *, kb_id, top_k: [
                {
                    "doc_id": 1,
                    "file_name": "a.md",
                    "chunk_index": 0,
                    "score": 0.9,
                    "text": "x",
                }
            ],
            checkpointer=saver,
        )
    )
    graph = rag_runtime.get_graph()
    thread = str(session.id)
    graph.invoke(
        {"question": "预热", "kb_id": kb.id},
        config={"configurable": {"thread_id": thread}},
    )
    assert graph.get_state({"configurable": {"thread_id": thread}}).values["question"]

    resp = client.delete(f"/api/chat/sessions/{session.id}", headers=auth_header(alice))
    assert resp.status_code == 204

    # 消息级联删除
    resp = client.get(
        f"/api/chat/sessions/{session.id}/messages", headers=auth_header(alice)
    )
    assert resp.status_code == 404  # 会话已删

    from sqlalchemy import select

    from app.models import ChatMessage

    assert db.scalar(select(ChatMessage).where(ChatMessage.id == msg.id)) is None

    # checkpoint 已清理（thread 状态为空）
    state = graph.get_state({"configurable": {"thread_id": thread}})
    assert state.values == {}


def test_session_crud_permissions(client, db):
    _admin, alice, kb = _setup(client, db)
    bob = make_user(db, "bob")

    resp = client.post(
        "/api/chat/sessions",
        json={"title": "我的会话", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 201
    sid = resp.json()["id"]

    # 改名
    resp = client.patch(
        f"/api/chat/sessions/{sid}",
        json={"title": "新标题"},
        headers=auth_header(alice),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"

    # 非归属 403
    resp = client.patch(
        f"/api/chat/sessions/{sid}",
        json={"title": "hack"},
        headers=auth_header(bob),
    )
    assert resp.status_code == 403
    resp = client.delete(f"/api/chat/sessions/{sid}", headers=auth_header(bob))
    assert resp.status_code == 403


# ---------- 检索调试 ----------


def test_retrieval_search_requires_membership(client, db):
    _admin, alice, kb = _setup(client, db)
    bob = make_user(db, "bob")
    resp = client.post(
        "/api/retrieval/search",
        json={"query": "请假", "kb_id": kb.id},
        headers=auth_header(bob),
    )
    assert resp.status_code == 403

    # 成员：未建索引 → 空结果（不报错）
    resp = client.post(
        "/api/retrieval/search",
        json={"query": "请假", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 200
    assert resp.json()["chunks"] == []


def test_retrieval_search_fingerprint_mismatch_409(client, db):
    _admin, alice, kb = _setup(client, db)
    from app.models import EmbedIndexMeta

    db.add(
        EmbedIndexMeta(
            kb_id=kb.id, embed_fingerprint="openai/other-model", dimension=4
        )
    )
    db.commit()
    resp = client.post(
        "/api/retrieval/search",
        json={"query": "请假", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 409
    assert "embedding_mismatch" in resp.json()["detail"]


def test_history_pagination_and_admin_filter(client, db):
    admin, alice, kb = _setup(client, db)
    _make_message(db, alice, kb, question="q1")
    _make_message(db, alice, kb, question="q2")

    # user 只看自己的
    resp = client.get("/api/chat/history", headers=auth_header(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2

    bob = make_user(db, "bob")
    resp = client.get("/api/chat/history", headers=auth_header(bob))
    assert resp.json()["total"] == 0

    # admin 按用户过滤
    resp = client.get(
        f"/api/chat/history?user_id={alice.id}", headers=auth_header(admin)
    )
    assert resp.json()["total"] == 2
