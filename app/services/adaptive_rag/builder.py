"""Adaptive RAG 图装配：条件边、有界循环、compile(checkpointer)。

边逻辑（architecture §5.2）：
START → normalize → classify
  clarification → abstain
  knowledge → retrieve → grade
    sufficient → generate → cite → validate → END
    not & rewrite_count < MAX → rewrite → retrieve
    not & rewrite_count ≥ MAX → abstain → cite → validate → END
generate 空答案 → abstain → cite → validate → END
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.core.config import settings as default_settings
from app.services.adaptive_rag.nodes import (
    abstain,
    cite,
    classify,
    make_generate_node,
    make_grade_node,
    make_retrieve_node,
    make_rewrite_node,
    normalize,
    validate,
)
from app.services.adaptive_rag.state import RagState


def build_graph(
    *,
    chat_model: Any = None,
    retriever: Callable[..., list[dict]] | None = None,
    checkpointer: Any = None,
    settings: Any = None,
    on_token: Callable[[str, str], None] | None = None,
):
    """组装并编译 Adaptive RAG 图。

    - chat_model / retriever 工厂注入（单测传 Scripted 模型与假检索）
    - checkpointer=None 时仍可运行（单测提速）；生产经 get_checkpointer() 注入
    - on_token 为默认回调，单请求可经 config.configurable.on_token 覆盖
    """
    cfg = settings or default_settings
    if chat_model is None:
        from app.services.llm import create_chat_streamer

        chat_model = create_chat_streamer(cfg)

    retrieve = make_retrieve_node(retriever, default_top_k=cfg.retrieval_top_k)
    grade = make_grade_node(
        threshold=cfg.retrieval_score_threshold,
        chat_model=chat_model,
        use_llm=cfg.grade_with_llm,
    )
    rewrite = make_rewrite_node(chat_model)
    generate = make_generate_node(chat_model, on_token=on_token)

    graph: StateGraph = StateGraph(RagState)
    graph.add_node("normalize", normalize)
    graph.add_node("classify", classify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite", rewrite)
    graph.add_node("generate", generate)
    graph.add_node("cite", cite)
    graph.add_node("validate", validate)
    graph.add_node("abstain", abstain)

    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "classify")

    def after_classify(state: RagState) -> str:
        return "abstain" if state.get("route") == "clarification" else "retrieve"

    def after_grade(state: RagState) -> str:
        if state.get("is_sufficient"):
            return "generate"
        max_attempts = state.get("max_rewrite_attempts") or cfg.max_rewrite_attempts
        if state.get("rewrite_count", 0) < max_attempts:
            return "rewrite"
        return "abstain"

    def after_generate(state: RagState) -> str:
        # 空答案 → abstain（cite/validate 兜底拒答文案）
        if not (state.get("answer") or "").strip():
            return "abstain"
        return "cite"

    graph.add_conditional_edges(
        "classify", after_classify, {"abstain": "abstain", "retrieve": "retrieve"}
    )
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        after_grade,
        {"generate": "generate", "rewrite": "rewrite", "abstain": "abstain"},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_conditional_edges(
        "generate", after_generate, {"abstain": "abstain", "cite": "cite"}
    )
    graph.add_edge("abstain", "cite")
    graph.add_edge("cite", "validate")
    graph.add_edge("validate", END)

    return graph.compile(checkpointer=checkpointer)
