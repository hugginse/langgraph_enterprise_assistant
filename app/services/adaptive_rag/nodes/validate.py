"""validate 节点：丢非法引用、产出 confidence / reasoning_summary、空答案降级。"""

from __future__ import annotations

from app.services.adaptive_rag.state import RagState

_ZERO_HIT = "未找到相关内容，请换个问法"


def _valid_key(c: dict) -> tuple:
    return (c.get("file_name", ""), c.get("chunk_index", 0))


def validate(state: RagState) -> dict:
    answer = state.get("answer") or ""
    relevant = state.get("relevant_chunks") or []
    citations = state.get("citations") or []
    errors = list(state.get("errors") or [])

    valid_keys = {_valid_key(c) for c in relevant}
    valid: list[dict] = []
    dropped = 0
    for c in citations:
        if _valid_key(c) in valid_keys:
            valid.append(c)
        else:
            dropped += 1
    if dropped:
        errors.append(f"validate: 丢弃 {dropped} 条非法引用")

    status = state.get("status") or "answered"
    if not answer.strip():
        answer = _ZERO_HIT
        status = "insufficient_evidence"

    if valid:
        confidence = max(min(float(c.get("score", 0.0)), 1.0), 0.0)
        summary = f"引用 {len(valid)}/{len(relevant)} 个相关片段"
    else:
        confidence = 0.0
        summary = state.get("grade_reason") or "无可引用片段"

    return {
        "answer": answer,
        "citations": valid,
        "confidence": round(confidence, 4),
        "reasoning_summary": summary,
        "status": status,
        "errors": errors,
    }
