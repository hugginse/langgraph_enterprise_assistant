"""问答、会话、消息、反馈、检索调试相关模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    kb_id: int
    session_id: int | None = None


class SessionCreate(BaseModel):
    title: str = Field(default="", max_length=255)
    kb_id: int | None = None


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionOut(BaseModel):
    id: int
    kb_id: int | None = None
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    session_id: int
    user_id: int
    kb_id: int | None = None
    question: str
    answer: str
    sources: list[dict[str, Any]] | None = None
    confidence: float | None = None
    status: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class HistoryPage(BaseModel):
    items: list[MessageOut]
    total: int
    page: int
    page_size: int


class FeedbackRequest(BaseModel):
    message_id: int
    score: Literal[1, -1]
    comment: str = Field(default="", max_length=1000)


class FeedbackOut(BaseModel):
    id: int
    message_id: int
    user_id: int
    score: int
    comment: str

    model_config = {"from_attributes": True}


class RetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_id: int | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class ChunkOut(BaseModel):
    kb_id: int | None = None
    doc_id: int | None = None
    file_name: str
    chunk_index: int
    score: float
    snippet: str


class SearchResult(BaseModel):
    chunks: list[ChunkOut]


class ReindexOut(BaseModel):
    status: str
    kb_id: int
