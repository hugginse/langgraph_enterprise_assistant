"""abstain 节点：固定拒答文案 + status=insufficient_evidence。"""

from __future__ import annotations

from app.services.adaptive_rag.state import RagState

CLARIFICATION_TEXT = "您的问题还不够具体，请补充关键信息后再试。"
ZERO_HIT_TEXT = "未找到相关内容，请换个问法"


def abstain(state: RagState) -> dict:
    if state.get("route") == "clarification" and not state.get("answer"):
        answer = CLARIFICATION_TEXT
        reason = "问题需要澄清"
    else:
        answer = ZERO_HIT_TEXT
        reason = state.get("refusal_reason") or "检索证据不足"
    return {
        "answer": answer,
        "status": "insufficient_evidence",
        "refusal_reason": reason,
        "is_sufficient": False,
    }
