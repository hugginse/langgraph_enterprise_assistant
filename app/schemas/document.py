"""文档相关模型。"""

from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    error_msg: str = ""
    chunk_count: int = 0
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
