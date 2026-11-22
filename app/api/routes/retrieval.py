"""检索调试接口：POST /api/retrieval/search → chunks + score。

按 kb 权限（登录；带 kb_id 时成员校验）；检索前指纹校验（409）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import login_required
from app.db import get_db
from app.models import KbMember, User
from app.schemas.chat import ChunkOut, RetrievalSearchRequest, SearchResult
from app.services import vector

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


def _visible_kb_ids(db: Session, user: User) -> list[int] | None:
    """admin → None 表示全部；user → 成员 kb id 列表。"""
    if user.role == "admin":
        return None
    return list(
        db.scalars(select(KbMember.kb_id).where(KbMember.user_id == user.id)).all()
    )


@router.post("/search", response_model=SearchResult)
def search(
    body: RetrievalSearchRequest,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> SearchResult:
    kb_ids: list[int] | None
    if body.kb_id is not None:
        member = True
        if user.role != "admin":
            member = (
                db.scalar(
                    select(KbMember).where(
                        KbMember.kb_id == body.kb_id, KbMember.user_id == user.id
                    )
                )
                is not None
            )
        if not member:
            raise HTTPException(status_code=403, detail="无权访问该知识库")
        kb_ids = [body.kb_id]
    else:
        kb_ids = _visible_kb_ids(db, user)

    chunks: list[ChunkOut] = []
    if kb_ids:
        for kid in kb_ids:
            try:
                rows = vector.search(
                    body.query, kb_id=kid, top_k=body.top_k, db=db
                )
            except vector.EmbeddingMismatchError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            for r in rows:
                chunks.append(
                    ChunkOut(
                        kb_id=kid,
                        doc_id=r.get("doc_id"),
                        file_name=r.get("file_name", ""),
                        chunk_index=r.get("chunk_index", 0),
                        score=float(r.get("score", 0.0)),
                        snippet=(r.get("text") or "")[:200],
                    )
                )
    chunks.sort(key=lambda c: c.score, reverse=True)
    limit = body.top_k or 10
    return SearchResult(chunks=chunks[: max(limit * 3, 10)])
