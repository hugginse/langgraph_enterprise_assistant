"""generate 节点：流式生成，逐块回调 on_token（禁止 invoke 后切片）。"""

from typing import Any, Callable

from langgraph.types import RunnableConfig

from app.services.adaptive_rag.prompts import GENERATE_SYSTEM, GENERATE_USER
from app.services.adaptive_rag.state import RagState
from app.services.adaptive_rag.stream_bridge import get_callback, stream_with_callback

_FALLBACK_ANSWER = "未找到相关内容，请换个问法"


def _format_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "（无检索结果）"
    return "\n".join(
        f"[{i}] {c.get('file_name', '?')}#{c.get('chunk_index', 0)} "
        f"(score={float(c.get('score', 0.0)):.2f})\n{c.get('text', '')}"
        for i, c in enumerate(chunks, 1)
    )


def _format_history(history: list[dict]) -> str:
    if not history:
        return "（无）"
    return "\n".join(
        f"Q: {h.get('question', '')}\nA: {(h.get('answer') or '')[:200]}"
        for h in history[-3:]
    )


def make_generate_node(
    chat_model: Any,
    on_token: Callable[[str, str], None] | None = None,
) -> Callable[..., dict]:
    def generate(state: RagState, config: RunnableConfig | None = None) -> dict:
        emit = get_callback(config, "on_node")
        if emit is not None:
            emit("generate")

        # 每请求回调优先于工厂默认回调
        token_cb = get_callback(config, "on_token") or on_token

        chunks = state.get("relevant_chunks") or []
        if not chunks:
            # 零命中兜底，不算错误
            return {"answer": _FALLBACK_ANSWER, "status": "insufficient_evidence"}

        answer = stream_with_callback(
            chat_model,
            system=GENERATE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": GENERATE_USER.format(
                        chunks=_format_chunks(chunks),
                        history=_format_history(state.get("history") or []),
                        question=state.get("normalized_question")
                        or state.get("question", ""),
                    ),
                }
            ],
            on_token=token_cb,
        ).strip()

        if not answer:
            return {"answer": "", "status": "insufficient_evidence"}
        return {"answer": answer, "status": "answered"}

    return generate
