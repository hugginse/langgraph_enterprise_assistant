"""认证与用户相关请求/响应模型。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str
    role: str
    status: int

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=64)
    role: str = Field(default="user", pattern="^(admin|user)$")


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    password: str | None = Field(default=None, min_length=6, max_length=128)
    status: int | None = Field(default=None, pattern="^[01]$")


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int
