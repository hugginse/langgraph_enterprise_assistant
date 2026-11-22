"""Chroma 向量库封装（M1 占位；M2/M3 接通检索与入库）。

约束（architecture §9）：建 collection 必须 metadata={"hnsw:space":"cosine"}。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def delete_collection(kb_id: int) -> None:
    """删除 kb_{id} collection；不存在时静默容忍。M3 接通真实实现。"""
    logger.info("delete_collection 占位 kb_id=%s（M3 接通）", kb_id)
