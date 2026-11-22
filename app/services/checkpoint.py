"""LangGraph checkpointer 工厂与级联清理。

约定（architecture §5.3）：
- thread_id = str(chat_session.id)，禁止与会话脱钩的随机 uuid
- PG saver 优先（langgraph-checkpoint-postgres，同一 PG）；依赖不可用回退 SQLite
  （checkpoints.db，gitignore），单测用 InMemorySaver 或 CHECKPOINT_ENABLED=false
- 删除会话 / 删除知识库时同步删除对应 thread 的 checkpoint 行
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db import SessionLocal  # noqa: F401  保证 engine 就绪（类型注释用）
from app.models import ChatSession

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_SAVER: object | None = None
_SAVER_KIND: str | None = None


def _pg_url() -> str:
    return settings.database_url.replace("postgresql+psycopg2://", "postgresql://")


def get_checkpointer():
    """返回 checkpointer 实例；CHECKPOINT_ENABLED=false 时返回 None。

    PG 优先，失败回退 SQLite 文件。进程内单例。
    """
    if not settings.checkpoint_enabled:
        return None
    global _SAVER, _SAVER_KIND
    with _LOCK:
        if _SAVER is not None:
            return _SAVER
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            saver = PostgresSaver.from_conn_string(_pg_url())
            saver.setup()
            _SAVER, _SAVER_KIND = saver, "postgres"
            logger.info("checkpointer: postgres (%s)", settings.checkpoint_table)
            return saver
        except Exception as exc:  # noqa: BLE001  回退路径
            logger.warning("PG checkpointer 不可用，回退 SQLite: %s", exc)
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = Path("checkpoints.db")
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        saver = SqliteSaver(conn)
        _SAVER, _SAVER_KIND = saver, "sqlite"
        logger.info("checkpointer: sqlite (%s)", db_path)
        return saver


def delete_thread(thread_id: str) -> None:
    """删除单个 thread 的 checkpoint（不存在时容忍）。"""
    saver = get_checkpointer()
    if saver is None:
        return
    try:
        saver.delete_thread(thread_id)
    except Exception as exc:  # noqa: BLE001  级联清理容忍不存在
        logger.warning("删除 checkpoint 失败 thread=%s: %s", thread_id, exc)


def delete_session_checkpoints(db, kb_id: int) -> int:
    """删除某知识库全部会话对应的 checkpoint 行；返回清理条数。

    thread_id = str(chat_session.id)。
    """
    saver = get_checkpointer()
    if saver is None:
        return 0
    session_ids = db.scalars(
        select(ChatSession.id).where(ChatSession.kb_id == kb_id)
    ).all()
    count = 0
    for sid in session_ids:
        try:
            saver.delete_thread(str(sid))
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除 checkpoint 失败 thread=%s: %s", sid, exc)
    return count


def reset_for_tests() -> None:
    """测试辅助：清空单例。"""
    global _SAVER, _SAVER_KIND
    with _LOCK:
        _SAVER, _SAVER_KIND = None, None
