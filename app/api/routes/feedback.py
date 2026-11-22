"""消息反馈 👍/👎（chat_feedback，UNIQUE(message_id, user_id) 幂等 upsert）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import login_required
from app.db import get_db
from app.models import ChatFeedback, ChatMessage, User
from app.schemas.chat import FeedbackOut, FeedbackRequest

router = APIRouter(prefix="/api/chat", tags=["feedback"])


@router.post(
    "/feedback", response_model=FeedbackOut, status_code=status.HTTP_200_OK
)
def submit_feedback(
    body: FeedbackRequest,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    msg = db.get(ChatMessage, body.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权评价该消息")

    existing = db.scalar(
        select(ChatFeedback).where(
            ChatFeedback.message_id == body.message_id,
            ChatFeedback.user_id == user.id,
        )
    )
    if existing is not None:
        existing.score = body.score
        existing.comment = body.comment
        db.commit()
        db.refresh(existing)
        return FeedbackOut.model_validate(existing)

    fb = ChatFeedback(
        message_id=body.message_id,
        user_id=user.id,
        score=body.score,
        comment=body.comment,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return FeedbackOut.model_validate(fb)
