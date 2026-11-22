"""看板统计模型。"""

from pydantic import BaseModel


class TrendPoint(BaseModel):
    date: str
    count: int


class DashboardOut(BaseModel):
    users: int
    kbs: int
    documents: int
    messages: int
    trend: list[TrendPoint]
