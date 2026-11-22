"""真流式单测：多段 delta 逐块到达回调，禁止 invoke 后切片。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from app.services.adaptive_rag.builder import build_graph
from app.services.adaptive_rag.nodes.abstain import ZERO_HIT_TEXT
from app.services.adaptive_rag.nodes.generate import make_generate_node
from tests.conftest import ScriptedChatModel

GOOD_CHUNKS = [
    ("thinking", "思考中……"),
    ("delta", "根据规定，"),
    ("delta", "员工请假需提前 "),
    ("delta", "3 个工作日 [1]"),
]


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


def test_generate_forwards_each_chunk_to_callback():
    """Scripted 分块 yield → on_token 按块收到多段（非整段切片）。"""
    model = ScriptedChatModel(chunks=GOOD_CHUNKS)
    events: list[tuple[str, str]] = []
    node = make_generate_node(model, on_token=lambda k, t: events.append((k, t)))

    out = node(
        {
            "relevant_chunks": _good_retriever("q", kb_id=1, top_k=4),
            "normalized_question": "请假提前几天？",
            "history": [],
        }
    )
    # 回调收到的分段与脚本完全一致（证明由 stream 驱动，而非固定长度切片）
    assert events == GOOD_CHUNKS
    deltas = [t for k, t in events if k == "delta"]
    assert len(deltas) == 3  # 多段 delta
    assert out["answer"] == "根据规定，员工请假需提前 3 个工作日 [1]"
    assert "思考中……" not in out["answer"]  # thinking 不进 answer


def test_graph_stream_multiple_deltas_via_config_callback():
    """经 config.configurable.on_token 注入：图内 generate 真流式吐多段。"""
    graph = build_graph(
        chat_model=ScriptedChatModel(chunks=GOOD_CHUNKS),
        retriever=_good_retriever,
        checkpointer=InMemorySaver(),
    )
    events: list[tuple[str, str]] = []
    nodes: list[str] = []
    final = None
    for step in graph.stream(
        {"question": "请假提前几天？", "kb_id": 1},
        config={
            "configurable": {
                "thread_id": "t-stream",
                "on_token": lambda k, t: events.append((k, t)),
                "on_node": lambda n: nodes.append(n),
            }
        },
    ):
        list(step)[0]
        final = list(step.values())[0]

    deltas = [t for k, t in events if k == "delta"]
    assert len(deltas) == 3
    assert deltas == ["根据规定，", "员工请假需提前 ", "3 个工作日 [1]"]
    assert final["answer"] == "根据规定，员工请假需提前 3 个工作日 [1]"
    # node 进度回调可用（ENABLE_NODE_SSE 的基础）
    assert "generate" in nodes


def test_node_events_order_before_tokens():
    """node(sources 类进度) 先于 delta。"""
    graph = build_graph(
        chat_model=ScriptedChatModel(chunks=GOOD_CHUNKS),
        retriever=_good_retriever,
        checkpointer=InMemorySaver(),
    )
    timeline: list[str] = []
    for step in graph.stream(
        {"question": "请假提前几天？", "kb_id": 1},
        config={
            "configurable": {
                "thread_id": "t-order",
                "on_token": lambda k, t: timeline.append(f"token:{k}"),
                "on_node": lambda n: timeline.append(f"node:{n}"),
            }
        },
    ):
        _ = step
    assert timeline.index("node:retrieve") < timeline.index("token:delta")
    assert timeline.index("node:generate") < timeline.index("token:delta")


def test_zero_hit_emits_no_tokens_and_fallback():
    """零命中：不进 generate、无 token、兜底文案不算错误。"""
    graph = build_graph(
        chat_model=ScriptedChatModel(chunks=GOOD_CHUNKS),
        retriever=lambda q, *, kb_id, top_k: [],
        checkpointer=InMemorySaver(),
    )
    events: list[tuple[str, str]] = []
    final = None
    for step in graph.stream(
        {"question": "请假提前几天？", "kb_id": 1},
        config={
            "configurable": {
                "thread_id": "t-zero",
                "on_token": lambda k, t: events.append((k, t)),
            }
        },
    ):
        final = list(step.values())[0]
    assert events == []  # 未进 generate，无伪流式
    assert final["answer"] == ZERO_HIT_TEXT
    assert final["status"] == "insufficient_evidence"
    assert final.get("citations", []) == []
