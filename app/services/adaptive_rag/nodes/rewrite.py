"""rewrite 节点：LLM 改写 + 确定性 fallback；拒绝空/过长；递增 rewrite_count。"""

from typing import Any, Callable

from langgraph.types import RunnableConfig

from app.services.adaptive_rag.prompts import REWRITE_SYSTEM, REWRITE_USER
from app.services.adaptive_rag.state import RagState
from app.services.adaptive_rag.stream_bridge import complete, get_callback

_MAX_REWRITE_LEN = 200

_TEMPLATES = [
    "{q} 详细规定",
    "关于 {q} 的说明",
    "{q} 相关制度",
]


def _deterministic_fallback(prev_query: str, attempt: int) -> str:
    template = _TEMPLATES[attempt % len(_TEMPLATES)]
    return template.format(q=prev_query.strip())[:_MAX_REWRITE_LEN]


def _valid(candidate: str) -> bool:
    candidate = (candidate or "").strip()
    return bool(candidate) and len(candidate) <= _MAX_REWRITE_LEN


def make_rewrite_node(chat_model: Any = None) -> Callable[..., dict]:
    def rewrite(state: RagState, config: RunnableConfig | None = None) -> dict:
        emit = get_callback(config, "on_node")
        if emit is not None:
            emit("rewrite")

        prev = state.get("active_query") or state.get("normalized_question") or ""
        history = state.get("history") or []
        history_text = "\n".join(
            f"Q: {h.get('question', '')}\nA: {(h.get('answer') or '')[:100]}" for h in history[-3:]
        ) or "（无）"

        candidate = ""
        if chat_model is not None:
            try:
                candidate = complete(
                    chat_model,
                    system=REWRITE_SYSTEM,
                    messages=[
                        {
                            "role": "user",
                            "content": REWRITE_USER.format(
                                history=history_text,
                                question=state.get("normalized_question") or prev,
                                prev_query=prev,
                            ),
                        }
                    ],
                ).strip()
            except Exception:  # noqa: BLE001  LLM 失败 → 确定性 fallback
                candidate = ""

        if not _valid(candidate):
            candidate = _deterministic_fallback(
                prev, state.get("rewrite_count", 0)
            )

        return {
            "active_query": candidate,
            "rewrite_count": state.get("rewrite_count", 0) + 1,
        }

    return rewrite
