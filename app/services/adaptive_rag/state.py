"""Adaptive RAG 图状态（architecture §5.1）。

约束：TypedDict 可序列化；不存 API Key、不存隐藏思维链；
rewrite_count 保证可终止。kb_id 供 retrieve 定位 collection。
"""

from typing import TypedDict


class RagState(TypedDict, total=False):
    # 输入
    question: str
    normalized_question: str
    top_k: int
    history: list[dict]
    kb_id: int
    # 检索
    active_query: str
    chunks: list[dict]
    relevant_chunks: list[dict]
    retrieval_attempts: int
    rewrite_count: int
    max_rewrite_attempts: int
    # 判定
    route: str  # knowledge | clarification
    is_sufficient: bool
    grade_reason: str
    refusal_reason: str
    # 生成
    answer: str
    citations: list[dict]
    confidence: float | None
    reasoning_summary: str
    status: str  # answered | insufficient_evidence
    # 可观测
    errors: list[str]
