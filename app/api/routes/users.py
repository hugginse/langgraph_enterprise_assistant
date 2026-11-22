"""用户管理（admin）：分页列表 / 创建 / 修改（含重置密码）/ 禁用。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import admin_required, hash_password
from app.db import get_db
from app.models import User
from app.schemas.auth import UserCreate, UserOut, UserPage, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=UserPage)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> UserPage:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    items = list(
        db.scalars(
            select(User).order_by(User.id).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return UserPage(
        items=[UserOut.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> UserOut:
    exists = db.scalar(select(User).where(User.username == body.username))
    if exists is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
        role=body.role,
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> UserOut:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.role is not None:
        user.role = body.role
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.status is not None:
        user.status = body.status
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", response_model=UserOut)
def disable_user(
    user_id: int,
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> UserOut:
    """禁用（status=0），不物理删。"""
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = 0
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
