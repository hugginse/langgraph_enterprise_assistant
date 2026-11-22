"""管理端看板统计（admin）。"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import admin_required
from app.db import get_db
from app.models import ChatMessage, Document, KnowledgeBase, User
from app.schemas.stats import DashboardOut, TrendPoint

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    _: User = Depends(admin_required),
    db: Session = Depends(get_db),
) -> DashboardOut:
    users = db.scalar(select(func.count()).select_from(User)) or 0
    kbs = db.scalar(select(func.count()).select_from(KnowledgeBase)) or 0
    documents = db.scalar(select(func.count()).select_from(Document)) or 0
    messages = db.scalar(select(func.count()).select_from(ChatMessage)) or 0

    # 近 7 天（含今天）每日消息数
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today - timedelta(days=6), datetime.min.time())
    rows = db.execute(
        select(func.date(ChatMessage.created_at), func.count())
        .where(ChatMessage.created_at >= start)
        .group_by(func.date(ChatMessage.created_at))
        .order_by(func.date(ChatMessage.created_at))
    ).all()
    counts = {str(d): int(c) for d, c in rows}

    trend = [
        TrendPoint(date=str(today - timedelta(days=6 - i)), count=counts.get(
            str(today - timedelta(days=6 - i)), 0
        ))
        for i in range(7)
    ]
    return DashboardOut(users=users, kbs=kbs, documents=documents, messages=messages, trend=trend)
