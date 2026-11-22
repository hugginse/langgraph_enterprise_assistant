"""SSE 事件顺序与真流式单测：sources 先于 delta、多段 delta、权限前置、落库。"""

from __future__ import annotations

import json

from langgraph.checkpoint.memory import InMemorySaver

from app.services import rag_runtime
from app.services.adaptive_rag import build_graph
from tests.conftest import ScriptedChatModel, add_member, auth_header, make_kb, make_user

GOOD_CHUNKS = [
    ("thinking", "思考：需要查请假天数……"),
    ("delta", "根据《员工请假管理办法》，"),
    ("delta", "员工请假需提前 "),
    ("delta", "3 个工作日 [1]"),
]

GOOD_RETRIEVER_CHUNKS = [
    {
        "doc_id": 1,
        "file_name": "员工请假管理办法.md",
        "chunk_index": 3,
        "score": 0.91,
        "text": "员工请假需提前 3 个工作日向直属主管申请。",
    }
]


def _good_retriever(q, *, kb_id, top_k):
    return list(GOOD_RETRIEVER_CHUNKS)


def _inject_graph(retriever, chunks=GOOD_CHUNKS):
    rag_runtime.set_graph(
        build_graph(
            chat_model=ScriptedChatModel(chunks=chunks),
            retriever=retriever,
            checkpointer=InMemorySaver(),
        )
    )


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if ev is not None:
            events.append((ev, data or {}))
    return events


def _setup_member(client, db):
    admin = make_user(db, "root", role="admin")
    user = make_user(db, "alice")
    kb = make_kb(db, "请假制度", created_by=admin.id)
    add_member(db, kb.id, user.id)
    return admin, user, kb


def test_ask_sse_order_and_true_streaming(client, db):
    """sources 先于 thinking/delta；delta 多段到达；done 收尾；消息落库。"""
    _user, alice, kb = _setup_member(client, db)
    _inject_graph(_good_retriever)

    resp = client.post(
        "/api/chat/ask",
        json={"question": "员工请假需要提前几天申请？", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(resp.text)
    names = [e for e, _ in events]

    # 顺序：sources → thinking → delta×N → done
    i_src = names.index("sources")
    i_think = names.index("thinking")
    deltas = [(i, p) for i, (e, p) in enumerate(events) if e == "delta"]
    i_done = names.index("done")
    assert i_src < i_think < deltas[0][0] < i_done
    # 多段 delta（真流式，非整段切片）
    assert len(deltas) == 3
    assert [p["text"] for _, p in deltas] == [
        "根据《员工请假管理办法》，",
        "员工请假需提前 ",
        "3 个工作日 [1]",
    ]
    # sources 内容真实
    src = events[i_src][1]["sources"]
    assert len(src) == 1
    assert src[0]["file_name"] == "员工请假管理办法.md"
    assert src[0]["score"] == 0.91

    # node 进度事件存在（ENABLE_NODE_SSE 默认开）
    assert "node" in names

    # done 落库字段
    done = events[i_done][1]
    assert done["session_id"] > 0
    assert done["message_id"] > 0
    assert done["status"] == "answered"
    assert done["confidence"] is not None

    # 消息落库：thinking 不落库
    msgs = client.get(
        f"/api/chat/sessions/{done['session_id']}/messages",
        headers=auth_header(alice),
    ).json()
    assert len(msgs) == 1
    m = msgs[0]
    assert m["question"] == "员工请假需要提前几天申请？"
    assert "3 个工作日" in m["answer"]
    assert "思考" not in m["answer"]  # thinking 不落库
    assert m["sources"][0]["file_name"] == "员工请假管理办法.md"
    assert m["confidence"] is not None
    assert m["status"] == "answered"


def test_ask_zero_hit_fallback(client, db):
    """零命中：sources: [] + 兜底文案，不算错误。"""
    _user, alice, kb = _setup_member(client, db)
    _inject_graph(lambda q, *, kb_id, top_k: [])

    resp = client.post(
        "/api/chat/ask",
        json={"question": "完全查不到的问题xyz", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    names = [e for e, _ in events]
    assert "sources" in names
    assert events[names.index("sources")][1]["sources"] == []
    done = events[names.index("done")][1]
    assert done["status"] == "insufficient_evidence"
    # 无 delta（未进 generate 伪流式）
    assert "delta" not in names
    msgs = client.get(
        f"/api/chat/sessions/{done['session_id']}/messages",
        headers=auth_header(alice),
    ).json()
    assert msgs[0]["answer"] == "未找到相关内容，请换个问法"


def test_ask_non_member_403_before_sse(client, db):
    """非成员 403，且不进 SSE（JSON 响应）。"""
    admin, alice, kb = _setup_member(client, db)
    bob = make_user(db, "bob")
    _inject_graph(_good_retriever)

    resp = client.post(
        "/api/chat/ask",
        json={"question": "请假几天", "kb_id": kb.id},
        headers=auth_header(bob),
    )
    assert resp.status_code == 403
    assert "event-stream" not in resp.headers.get("content-type", "")
    assert resp.json()["detail"] == "无权访问该知识库"


def test_ask_requires_auth(client, db):
    _user, alice, kb = _setup_member(client, db)
    resp = client.post(
        "/api/chat/ask", json={"question": "x", "kb_id": kb.id}
    )
    assert resp.status_code == 401


def test_ask_fingerprint_mismatch_409(client, db):
    """索引指纹与当前 Embedder 不一致 → 409，禁止静默用错向量。"""
    _user, alice, kb = _setup_member(client, db)
    from app.models import EmbedIndexMeta

    db.add(
        EmbedIndexMeta(
            kb_id=kb.id, embed_fingerprint="openai/text-embedding-3-small", dimension=8
        )
    )
    db.commit()
    _inject_graph(_good_retriever)

    resp = client.post(
        "/api/chat/ask",
        json={"question": "请假几天", "kb_id": kb.id},
        headers=auth_header(alice),
    )
    assert resp.status_code == 409
    assert "embedding_mismatch" in resp.json()["detail"]


def test_ask_unknown_kb_404(client, db):
    _user, alice, _kb = _setup_member(client, db)
    resp = client.post(
        "/api/chat/ask",
        json={"question": "x", "kb_id": 99999},
        headers=auth_header(alice),
    )
    assert resp.status_code == 404
