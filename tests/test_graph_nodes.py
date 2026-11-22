"""图节点与终止条件单测：条件边路由、rewrite 上限、空答案、非法 citation。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from app.services.adaptive_rag.builder import build_graph
from app.services.adaptive_rag.nodes.abstain import ZERO_HIT_TEXT, abstain
from app.services.adaptive_rag.nodes.cite import cite
from app.services.adaptive_rag.nodes.classify import classify
from app.services.adaptive_rag.nodes.normalize import normalize
from app.services.adaptive_rag.nodes.rewrite import make_rewrite_node
from app.services.adaptive_rag.nodes.validate import validate
from tests.conftest import ScriptedChatModel


def _good_retriever(q, *, kb_id, top_k):
    return [
        {
            "doc_id": 1,
            "file_name": "员工请假管理办法.md",
            "chunk_index": 3,
            "score": 0.91,
            "text": "员工请假需提前 3 个工作日向直属主管申请。",
        }
    ]


def _bad_retriever(q, *, kb_id, top_k):
    return [
        {"doc_id": 1, "file_name": "无关.md", "chunk_index": 0, "score": 0.05, "text": "噪声"}
    ]


def _run(graph, question, **state_extra):
    events = list(
        graph.stream(
            {"question": question, "kb_id": 1, **state_extra},
            config={"configurable": {"thread_id": "t-test"}},
        )
    )
    return [list(e)[0] for e in events], list(events[-1].values())[0]


# ---------- 基础节点 ----------


def test_classify_empty_to_clarification():
    assert classify({"normalized_question": ""})["route"] == "clarification"


def test_classify_normal_to_knowledge():
    assert classify({"normalized_question": "请假几天"})["route"] == "knowledge"


def test_classify_overlong_to_clarification():
    assert classify({"normalized_question": "长" * 1001})["route"] == "clarification"


def test_normalize_strips_and_collapses():
    out = normalize({"question": "  请假   天数  "})
    assert out["normalized_question"] == "请假 天数"
    assert out["active_query"] == "请假 天数"


def test_normalize_short_with_history_resolves():
    out = normalize({"question": "那三天?", "history": [{"question": "年假怎么休", "answer": "…"}]})
    assert "年假怎么休" in out["normalized_question"]


def test_abstain_clarification_text():
    out = abstain({"route": "clarification"})
    assert out["status"] == "insufficient_evidence"
    assert out["answer"]


def test_abstain_zero_hit_text():
    out = abstain({"route": "knowledge"})
    assert out["answer"] == ZERO_HIT_TEXT
    assert out["status"] == "insufficient_evidence"


def test_rewrite_increments_and_fallback_on_llm_failure():
    node = make_rewrite_node(ScriptedChatModel(fail=True))
    out = node({"active_query": "请假", "rewrite_count": 0})
    assert out["rewrite_count"] == 1
    assert out["active_query"]  # 确定性 fallback 非空
    assert out["active_query"] != ""


def test_rewrite_rejects_overlong_llm_output():
    long_text = "长" * 300
    node = make_rewrite_node(ScriptedChatModel(chunks=[("delta", long_text)]))
    out = node({"active_query": "请假", "rewrite_count": 0})
    assert len(out["active_query"]) <= 200
    assert out["rewrite_count"] == 1


def test_cite_only_from_relevant_chunks():
    state = {
        "answer": "需提前 3 天 [1]，另有 [99] 编造引用",
        "relevant_chunks": [
            {"doc_id": 1, "file_name": "a.md", "chunk_index": 0, "score": 0.9, "text": "…"}
        ],
    }
    out = cite(state)
    assert len(out["citations"]) == 1
    assert out["citations"][0]["ref"] == 1


def test_validate_drops_illegal_citation():
    state = {
        "answer": "答案 [1] 和 [7]",
        "status": "answered",
        "relevant_chunks": [
            {"doc_id": 1, "file_name": "a.md", "chunk_index": 0, "score": 0.8, "text": "…"}
        ],
        "citations": [
            {"file_name": "a.md", "chunk_index": 0, "score": 0.8},
            {"file_name": "ghost.md", "chunk_index": 9, "score": 0.7},
        ],
    }
    out = validate(state)
    assert len(out["citations"]) == 1
    assert out["citations"][0]["file_name"] == "a.md"
    assert out["confidence"] > 0
    assert any("非法引用" in e for e in out["errors"])


def test_validate_empty_answer_degrades():
    out = validate({"answer": "  ", "status": "answered", "relevant_chunks": [], "citations": []})
    assert out["answer"] == ZERO_HIT_TEXT
    assert out["status"] == "insufficient_evidence"


# ---------- 图级：条件边与有界循环 ----------


def test_clarification_routes_to_abstain_without_retrieve():
    def retriever(q, *, kb_id, top_k):
        raise AssertionError("clarification 不应触发 retrieve")

    graph = build_graph(
        chat_model=ScriptedChatModel(), retriever=retriever, checkpointer=InMemorySaver()
    )
    steps, final = _run(graph, "")
    assert "retrieve" not in steps
    assert "abstain" in steps
    assert final["status"] == "insufficient_evidence"


def test_rewrite_hits_max_and_stops():
    """检索始终不达标 → 有界 rewrite 循环，达上限必停（不无限循环）。"""
    graph = build_graph(
        chat_model=ScriptedChatModel(chunks=[("delta", "改写查询")]),
        retriever=_bad_retriever,
        checkpointer=InMemorySaver(),
    )
    steps, final = _run(graph, "完全无关的问题")
    assert steps.count("rewrite") == 2  # MAX_REWRITE_ATTEMPTS 默认 2
    assert steps.count("retrieve") == 3
    assert final["status"] == "insufficient_evidence"
    assert final["answer"] == ZERO_HIT_TEXT


def test_sufficient_reaches_generate_and_answered():
    graph = build_graph(
        chat_model=ScriptedChatModel(
            chunks=[("delta", "需提前 3 天"), ("delta", "申请 [1]")]
        ),
        retriever=_good_retriever,
        checkpointer=InMemorySaver(),
    )
    steps, final = _run(graph, "请假提前几天申请？")
    assert "generate" in steps
    assert steps[-1] == "validate"
    assert final["status"] == "answered"
    assert final["answer"] == "需提前 3 天申请 [1]"
    assert len(final["citations"]) == 1


def test_empty_answer_degrades_to_abstain():
    """generate 空答案 → abstain → cite → validate。"""
    graph = build_graph(
        chat_model=ScriptedChatModel(chunks=[]),  # 不吐任何 token
        retriever=_good_retriever,
        checkpointer=InMemorySaver(),
    )
    steps, final = _run(graph, "请假提前几天？")
    assert "generate" in steps
    i_gen, i_abstain = steps.index("generate"), steps.index("abstain")
    assert i_abstain > i_gen
    assert final["answer"] == ZERO_HIT_TEXT
    assert final["status"] == "insufficient_evidence"
