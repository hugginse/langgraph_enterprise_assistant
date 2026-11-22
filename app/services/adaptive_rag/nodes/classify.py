"""classify 节点：轻量路由 knowledge / clarification（确定性规则）。"""

from __future__ import annotations

from app.services.adaptive_rag.state import RagState

_MAX_LEN = 1000


def classify(state: RagState) -> dict:
    q = (state.get("normalized_question") or "").strip()
    if not q or len(q) > _MAX_LEN:
        return {"route": "clarification"}
    return {"route": "knowledge"}
