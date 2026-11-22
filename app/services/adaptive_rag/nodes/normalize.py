"""normalize 节点：清洗问题；可选结合 history 做轻量指代消解。"""

from __future__ import annotations

import re

from app.services.adaptive_rag.state import RagState

_MAX_QUESTION = 2000


def normalize(state: RagState) -> dict:
    question = (state.get("question") or "").strip()
    question = re.sub(r"\s+", " ", question)
    if len(question) > _MAX_QUESTION:
        question = question[:_MAX_QUESTION]

    history = state.get("history") or []
    # 轻量指代消解：问题过短且有历史时，拼上最近一轮问题的实体
    if question and len(question) <= 8 and history:
        last_q = (history[-1].get("question") or "").strip()
        if last_q:
            question = f"{last_q} 相关的 {question}"

    active = state.get("active_query") or question
    return {
        "normalized_question": question,
        "active_query": active,
        "retrieval_attempts": state.get("retrieval_attempts", 0),
        "rewrite_count": state.get("rewrite_count", 0),
        "errors": state.get("errors", []),
    }
