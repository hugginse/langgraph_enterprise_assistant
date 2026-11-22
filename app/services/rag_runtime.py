"""问答图运行时：进程级单例 + 测试注入点。

生产：build_graph(retriever=default_retriever, checkpointer=get_checkpointer())
测试：set_graph(build_graph(chat_model=Scripted..., ...))
"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_GRAPH: Any = None


def get_graph():
    global _GRAPH
    with _LOCK:
        if _GRAPH is None:
            from app.services.adaptive_rag import build_graph
            from app.services.checkpoint import get_checkpointer
            from app.services.vector import default_retriever

            _GRAPH = build_graph(
                retriever=default_retriever,
                checkpointer=get_checkpointer(),
            )
        return _GRAPH


def set_graph(graph: Any) -> None:
    global _GRAPH
    with _LOCK:
        _GRAPH = graph


def reset_graph() -> None:
    global _GRAPH
    with _LOCK:
        _GRAPH = None
