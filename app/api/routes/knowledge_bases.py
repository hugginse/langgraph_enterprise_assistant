"""知识库 CRUD 与成员授权（admin 管理；user 仅成员可见）。

M1 阶段删除为 DB 级级联（documents 记录、uploads 物理文件、sessions、messages）；
Chroma collection 与 checkpoint 清理以 try/except 占位，M3 接通。
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import admin_required, login_required
from app.db import get_db
from app.models import ChatMessage, ChatSession, Document, KbMember, KnowledgeBase, User
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
    """级联物理删除：documents 记录 → uploads 物理文件 → sessions/messages → 占位清理。"""
    get_kb_or_404(db, kb_id)

    # uploads 物理文件
    docs = db.scalars(select(Document).where(Document.kb_id == kb_id)).all()
    upload_root = Path(settings.upload_dir)
    for doc in docs:
        path = upload_root / doc.stored_name
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:  # 容忍：文件缺失不阻断
            logger.warning("删除上传文件失败 %s: %s", path, exc)

    # DB 级联（表级外键已 ondelete，这里显式执行以覆盖未开 FK 约束的场景）
    session_ids = select(ChatSession.id).where(ChatSession.kb_id == kb_id)
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    db.execute(delete(ChatSession).where(ChatSession.kb_id == kb_id))
    db.execute(delete(KbMember).where(KbMember.kb_id == kb_id))
    db.execute(delete(Document).where(Document.kb_id == kb_id))
    db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    db.commit()

    # Chroma collection 与 checkpoint 清理：M1 占位，容忍不存在；M3 接通
    try:
        from app.services import vector  # noqa: PLC0415

        vector.delete_collection(kb_id)
    except Exception:  # noqa: BLE001  M1 阶段允许失败
        logger.info("Chroma 清理占位（M3 接通）kb_id=%s", kb_id)
    try:
        from app.services import checkpoint  # noqa: PLC0415

        checkpoint.delete_session_checkpoints(db, kb_id)
    except Exception:  # noqa: BLE001  M1 阶段允许失败
        logger.info("checkpoint 清理占位（M3 接通）kb_id=%s", kb_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
