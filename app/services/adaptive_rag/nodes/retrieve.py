"""retrieve 节点：按 active_query + 当前 kb_id 调注入的 retriever。"""

from typing import Callable

from langgraph.types import RunnableConfig

from app.services.adaptive_rag.state import RagState

# search(query, *, kb_id, top_k) -> list[dict]（含 score/file_name/chunk_index/text）
Retriever = Callable[..., list[dict]]


def make_retrieve_node(
    retriever: Retriever | None,
    *,
    default_top_k: int = 4,
) -> Callable[..., dict]:
    def retrieve(state: RagState, config: RunnableConfig | None = None) -> dict:
        from app.services.adaptive_rag.stream_bridge import get_callback

        emit = get_callback(config, "on_node")
        if emit is not None:
            emit("retrieve")

        query = state.get("active_query") or state.get("normalized_question") or ""
        kb_id = state.get("kb_id")
        top_k = state.get("top_k") or default_top_k
        attempts = state.get("retrieval_attempts", 0) + 1

        chunks: list[dict] = []
        errors = list(state.get("errors") or [])
        if retriever is not None and query and kb_id is not None:
            try:
                chunks = list(retriever(query, kb_id=kb_id, top_k=top_k)) or []
            except Exception as exc:  # noqa: BLE001  检索失败记入 errors 不中断图
                errors.append(f"retrieve: {exc}")
                chunks = []
        return {"chunks": chunks, "retrieval_attempts": attempts, "errors": errors}

    return retrieve
