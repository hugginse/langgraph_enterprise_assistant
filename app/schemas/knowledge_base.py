"""知识库与成员相关模型。"""

from pydantic import BaseModel, Field


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class KbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class KbOut(BaseModel):
    id: int
    name: str
    description: str
    created_by: int | None = None
    status: int = 1

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    user_id: int


class MemberOut(BaseModel):
    id: int
    user_id: int
    username: str = ""
    nickname: str = ""

    model_config = {"from_attributes": True}
