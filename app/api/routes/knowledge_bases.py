"""知识库 CRUD 与成员授权（admin 管理；user 仅成员可见）。

M1 阶段删除为 DB 级级联（documents 记录、uploads 物理文件、sessions、messages）；
Chroma collection 与 checkpoint 清理以 try/except 占位，M3 接通。
"""

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import admin_required, login_required
from app.db import get_db
from app.models import (
    ChatMessage,
    ChatSession,
    Document,
    EmbedIndexMeta,
    KbMember,
    KnowledgeBase,
    User,
)
from app.schemas.chat import ReindexOut
from app.schemas.knowledge_base import KbCreate, KbOut, KbUpdate, MemberAdd, MemberOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def get_kb_or_404(db: Session, kb_id: int) -> KnowledgeBase:
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


def require_kb_access(
    user: User, db: Session, kb_id: int
) -> KnowledgeBase:
    """后端强校验：admin 全部；user 必须是成员。"""
    kb = get_kb_or_404(db, kb_id)
    if user.role == "admin":
        return kb
    member = db.scalar(
        select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user.id)
    )
    if member is None:
        # 非成员对不存在的库统一 404，存在的库 403
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    return kb


@router.get("", response_model=list[KbOut])
def list_kbs(
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> list[KbOut]:
    if user.role == "admin":
        rows = db.scalars(
            select(KnowledgeBase).order_by(KnowledgeBase.id)
        ).all()
    else:
        rows = db.scalars(
            select(KnowledgeBase)
            .join(KbMember, KbMember.kb_id == KnowledgeBase.id)
            .where(KbMember.user_id == user.id)
            .order_by(KnowledgeBase.id)
        ).all()
    return [KbOut.model_validate(kb) for kb in rows]


@router.post("", response_model=KbOut, status_code=status.HTTP_201_CREATED)
def create_kb(
    body: KbCreate,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> KbOut:
    kb = KnowledgeBase(name=body.name, description=body.description, status=1)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return KbOut.model_validate(kb)


@router.put("/{kb_id}", response_model=KbOut)
def update_kb(
    kb_id: int,
    body: KbUpdate,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> KbOut:
    kb = get_kb_or_404(db, kb_id)
    if body.name is not None:
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    db.commit()
    db.refresh(kb)
    return KbOut.model_validate(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kb(
    kb_id: int,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> Response:
    """级联物理删除：session ids 先收集 → checkpoint → Chroma → uploads → DB 行。

    任一步失败整体回滚（DB 部分单事务；外部资源清理在 DB 提交前执行失败则回滚）。
    """
    get_kb_or_404(db, kb_id)

    # 1) 先收集会话 id（删行前），清理各 thread checkpoint
    session_ids = list(
        db.scalars(select(ChatSession.id).where(ChatSession.kb_id == kb_id)).all()
    )
    from app.services import checkpoint as ckpt  # noqa: PLC0415

    for sid in session_ids:
        ckpt.delete_thread(str(sid))

    # 2) Chroma collection（不存在时容忍）
    from app.services import vector  # noqa: PLC0415

    vector.delete_collection(kb_id)

    # 3) uploads 物理文件
    docs = db.scalars(select(Document).where(Document.kb_id == kb_id)).all()
    upload_root = Path(settings.upload_dir)
    for doc in docs:
        path = upload_root / doc.stored_name
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:  # 容忍：文件缺失不阻断
            logger.warning("删除上传文件失败 %s: %s", path, exc)

    # 4) DB 单事务级联（表级外键已 ondelete，显式执行保证顺序清晰）
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    db.execute(delete(ChatSession).where(ChatSession.kb_id == kb_id))
    db.execute(delete(KbMember).where(KbMember.kb_id == kb_id))
    db.execute(delete(Document).where(Document.kb_id == kb_id))
    db.execute(delete(EmbedIndexMeta).where(EmbedIndexMeta.kb_id == kb_id))
    db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{kb_id}/reindex", response_model=ReindexOut)
def reindex_kb_endpoint(
    kb_id: int,
    background_tasks: BackgroundTasks,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> ReindexOut:
    """换 Embed 模型后重建向量：清空该库向量 → 全量重新入库（异步）。"""
    get_kb_or_404(db, kb_id)
    from app.services.ingest import reindex_kb  # noqa: PLC0415

    background_tasks.add_task(reindex_kb, kb_id)
    return ReindexOut(status="queued", kb_id=kb_id)


# ---------- 成员 ----------


@router.get("/{kb_id}/members", response_model=list[MemberOut])
def list_members(
    kb_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    require_kb_access(user, db, kb_id)
    rows = db.execute(
        select(KbMember, User)
        .join(User, User.id == KbMember.user_id)
        .where(KbMember.kb_id == kb_id)
        .order_by(KbMember.id)
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=m.user_id,
            username=u.username,
            nickname=u.nickname,
        )
        for m, u in rows
    ]


@router.post("/{kb_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    kb_id: int,
    body: MemberAdd,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> MemberOut:
    get_kb_or_404(db, kb_id)
    target = db.scalar(select(User).where(User.id == body.user_id))
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    exists = db.scalar(
        select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == body.user_id)
    )
    if exists is not None:
        raise HTTPException(status_code=400, detail="已是成员")
    member = KbMember(kb_id=kb_id, user_id=body.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return MemberOut(
        id=member.id,
        user_id=member.user_id,
        username=target.username,
        nickname=target.nickname,
    )


@router.delete("/{kb_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    kb_id: int,
    user_id: int,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> Response:
    get_kb_or_404(db, kb_id)
    member = db.scalar(
        select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user_id)
    )
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
