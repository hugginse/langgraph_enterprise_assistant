"""cite 节点：仅从 relevant_chunks 构建引用，模型不得发明 id。"""

from __future__ import annotations

import re

from app.services.adaptive_rag.state import RagState

# 匹配 [1] / [1,2] / [1][2] 等引用标记
_CITE_RE = re.compile(r"\[(\d{1,2})\]")


def cite(state: RagState) -> dict:
    answer = state.get("answer") or ""
    relevant = state.get("relevant_chunks") or []
    if not answer or not relevant:
        return {"citations": []}

    seen: set[int] = set()
    citations: list[dict] = []
    for match in _CITE_RE.finditer(answer):
        idx = int(match.group(1))
        if idx in seen or not (1 <= idx <= len(relevant)):
            continue
        seen.add(idx)
        chunk = relevant[idx - 1]
        citations.append(
            {
                "ref": idx,
                "doc_id": chunk.get("doc_id"),
                "file_name": chunk.get("file_name", ""),
                "chunk_index": chunk.get("chunk_index", 0),
                "score": float(chunk.get("score", 0.0)),
                "snippet": (chunk.get("text") or "")[:200],
            }
        )
    return {"citations": citations}
