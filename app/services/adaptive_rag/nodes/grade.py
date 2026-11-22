"""grade 节点：默认分数阈值规则；GRADE_WITH_LLM 时可用 LLM，失败必须回退规则。"""

from typing import Any, Callable

from langgraph.types import RunnableConfig

from app.services.adaptive_rag.prompts import GRADE_SYSTEM, GRADE_USER
from app.services.adaptive_rag.state import RagState
from app.services.adaptive_rag.stream_bridge import complete, get_callback


def _rule_grade(chunks: list[dict], threshold: float) -> tuple[bool, list[dict], str]:
    relevant = [c for c in chunks if float(c.get("score", 0.0)) >= threshold]
    if not relevant:
        return False, [], f"无片段达到分数阈值 {threshold}"
    best = max(float(c.get("score", 0.0)) for c in relevant)
    return True, relevant, f"{len(relevant)} 个片段过阈值（最高 {best:.2f}）"


def _llm_grade(
    chat_model: Any, question: str, chunks: list[dict]
) -> tuple[bool, str] | None:
    """LLM 判定；任何失败返回 None（调用方回退规则）。"""
    try:
        lines = [
            f"[{i}] (score={c.get('score', 0):.2f}) {c.get('text', '')[:300]}"
            for i, c in enumerate(chunks, 1)
        ]
        out = complete(
            chat_model,
            system=GRADE_SYSTEM,
            messages=[
                {"role": "user", "content": GRADE_USER.format(
                    question=question, chunks="\n".join(lines)
                )}
            ],
        )
        first = (out.strip().splitlines() or [""])[0].strip().lower()
        if first.startswith("sufficient"):
            return True, out.strip()[:200]
        if first.startswith("insufficient"):
            return False, out.strip()[:200]
        return None
    except Exception:  # noqa: BLE001  LLM 失败必须回退规则
        return None


def make_grade_node(
    *,
    threshold: float = 0.3,
    chat_model: Any = None,
    use_llm: bool = False,
) -> Callable[..., dict]:
    def grade(state: RagState, config: RunnableConfig | None = None) -> dict:
        emit = get_callback(config, "on_node")
        if emit is not None:
            emit("grade")

        chunks = state.get("chunks") or []
        question = state.get("normalized_question") or state.get("question") or ""

        sufficient, relevant, reason = _rule_grade(chunks, threshold)
        if use_llm and chat_model is not None and chunks:
            llm_result = _llm_grade(chat_model, question, chunks)
            if llm_result is not None:
                sufficient, reason = llm_result
                relevant = (
                    [c for c in chunks if float(c.get("score", 0.0)) >= threshold]
                    if sufficient
                    else []
                )

        return {
            "is_sufficient": sufficient,
            "relevant_chunks": relevant if sufficient else [],
            "grade_reason": reason,
            "refusal_reason": "" if sufficient else reason,
        }

    return grade
