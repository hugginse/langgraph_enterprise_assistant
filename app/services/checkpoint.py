"""LangGraph checkpointer 工厂与级联清理（M1 占位；M2 完整实现）。

约定（architecture §5.3）：thread_id = str(chat_session.id)。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_checkpointer() -> Any:
    """PG 优先 / SQLite 回退；M2 实现。"""
    raise NotImplementedError("checkpointer 将在 M2 实现")


def delete_session_checkpoints(db: Session, kb_id: int) -> None:
    """删除该知识库全部会话对应的 checkpoint 行（M3 接通真实表）。"""
    logger.info("checkpoint 级联清理占位 kb_id=%s（M3 接通）", kb_id)
    _ = (db, kb_id, sa_delete)
