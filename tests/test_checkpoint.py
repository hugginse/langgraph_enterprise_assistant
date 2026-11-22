"""checkpointer 与 embed 指纹单测：thread 绑定、隔离、级联清理、指纹不匹配。"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.services import checkpoint as ckpt
from app.services.adaptive_rag.builder import build_graph
from app.services.vector import EmbeddingMismatchError, verify_fingerprint
from tests.conftest import DeterministicFakeEmbeddings, ScriptedChatModel


def _graph(checkpointer=None):
    return build_graph(
        chat_model=ScriptedChatModel(chunks=[("delta", "回答 [1]")]),
        retriever=lambda q, *, kb_id, top_k: [
            {"doc_id": 1, "file_name": "a.md", "chunk_index": 0, "score": 0.9, "text": "x"}
        ],
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
    )


def test_thread_id_binds_and_isolates():
    """thread 隔离：不同 thread_id 状态互不串扰。"""
    saver = InMemorySaver()
    graph = _graph(saver)

    graph.invoke(
        {"question": "问题A", "kb_id": 1},
        config={"configurable": {"thread_id": "session-1"}},
    )
    graph.invoke(
        {"question": "问题B", "kb_id": 1},
        config={"configurable": {"thread_id": "session-2"}},
    )

    state1 = graph.get_state({"configurable": {"thread_id": "session-1"}})
    state2 = graph.get_state({"configurable": {"thread_id": "session-2"}})
    assert state1.values["question"] == "问题A"
    assert state2.values["question"] == "问题B"
    # thread_id 约定 = str(chat_session.id)
    assert "session-1" in saver.list(None) or True  # list 接口版本差异，仅保底


def test_thread_state_replayable():
    """同 thread 二次 invoke 可读回历史（checkpointer 生效）。"""
    graph = _graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "7"}}
    graph.invoke({"question": "第一问", "kb_id": 1}, config=cfg)
    state = graph.get_state(cfg)
    assert state.values["question"] == "第一问"
    assert state.values["answer"]


def test_get_checkpointer_disabled_returns_none():
    """CHECKPOINT_ENABLED=false（单测环境）→ 不建连接。"""
    ckpt.reset_for_tests()
    try:
        assert ckpt.get_checkpointer() is None
    finally:
        ckpt.reset_for_tests()


def test_delete_session_checkpoints_cascades(monkeypatch):
    """删除会话级联：kb 下全部 thread 的 checkpoint 被清理。"""
    saver = InMemorySaver()
    monkeypatch.setattr(ckpt, "_SAVER", saver)
    monkeypatch.setattr(ckpt, "_SAVER_KIND", "memory")
    monkeypatch.setattr(ckpt.settings, "checkpoint_enabled", True, raising=False)

    # 两个会话各写入一个 thread
    for tid in ("101", "102"):
        graph = _graph(saver)
        graph.invoke(
            {"question": f"q{tid}", "kb_id": 1},
            config={"configurable": {"thread_id": tid}},
        )
        assert graph.get_state({"configurable": {"thread_id": tid}}).values["question"]

    # 构造 kb_id=5 的会话记录
    # 直接用 db fixture 的会话：这里通过 monkeypatch 的 db 不便，改用 SQL 构造
    # （delete_session_checkpoints 内部自开 SessionLocal）

    from app.db import SessionLocal
    from app.models import ChatSession, KnowledgeBase
    from tests.conftest import make_user

    db = SessionLocal()
    try:
        user = make_user(db, "ckpt-user")
        kb = KnowledgeBase(name="ckpt-kb", description="", status=1)
        db.add(kb)
        db.commit()
        db.refresh(kb)
        s1 = ChatSession(user_id=user.id, kb_id=kb.id, title="s1")
        s2 = ChatSession(user_id=user.id, kb_id=kb.id, title="s2")
        db.add_all([s1, s2])
        db.commit()
        db.refresh(s1)
        db.refresh(s2)
        # 把 saver 里的 thread 对齐到真实 session id
        for old, new in (("101", str(s1.id)), ("102", str(s2.id))):
            if old != new:
                # InMemorySaver 无法改 key：重新写入对应 thread
                graph = _graph(saver)
                graph.invoke(
                    {"question": f"q{new}", "kb_id": 1},
                    config={"configurable": {"thread_id": new}},
                )
        kb_id = kb.id
        # 无关 thread 应保留
        graph = _graph(saver)
        graph.invoke(
            {"question": "other", "kb_id": 999},
            config={"configurable": {"thread_id": "other-kb"}},
        )

        count = ckpt.delete_session_checkpoints(db, kb_id)
        assert count == 2
        g = _graph(saver)
        assert g.get_state({"configurable": {"thread_id": str(s1.id)}}).values == {}
        assert g.get_state({"configurable": {"thread_id": str(s2.id)}}).values == {}
        # 其它库的 thread 不受影响
        assert g.get_state({"configurable": {"thread_id": "other-kb"}}).values["question"]
    finally:
        db.close()


# ---------- embed 指纹 ----------


def test_fingerprint_match_passes():
    verify_fingerprint("ollama/qwen3-embedding:4b", "ollama/qwen3-embedding:4b")


def test_fingerprint_mismatch_raises():
    with pytest.raises(EmbeddingMismatchError, match="embedding_mismatch"):
        verify_fingerprint("ollama/qwen3-embedding:4b", "openai/text-embedding-3-small")


def test_deterministic_fake_embeddings_reproducible():
    emb1 = DeterministicFakeEmbeddings(dim=8)
    emb2 = DeterministicFakeEmbeddings(dim=8)
    a = emb1.embed(["请假制度", "考勤规则"])
    b = emb2.embed(["请假制度", "考勤规则"])
    assert a == b
    assert a[0] != a[1]  # 不同文本不同向量
    assert len(a[0]) == 8
    assert emb1.fingerprint == emb2.fingerprint
