"""Chroma 向量库封装（检索/入库实现 M3 接通）。

约束（architecture §9）：
- 建 collection 必须 metadata={"hnsw:space":"cosine"}（分数阈值语义依赖）
- 分块 id：doc_{doc_id}_chunk_{i}；metadata：doc_id / file_name / chunk_index
- Embed 指纹不一致拒绝检索，要求 reindex（见 verify_fingerprint）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EmbeddingMismatchError(Exception):
    """当前 Embedder.fingerprint 与索引指纹不一致（embedding_mismatch）。"""


def verify_fingerprint(index_fingerprint: str, current_fingerprint: str) -> None:
    """检索前校验：不一致必须显式报错，禁止静默用错向量。"""
    if index_fingerprint and current_fingerprint and index_fingerprint != current_fingerprint:
        raise EmbeddingMismatchError(
            f"embedding_mismatch: 索引={index_fingerprint} 当前={current_fingerprint}，"
            "请执行 POST /knowledge-bases/{{id}}/reindex 重建向量"
        )


def delete_collection(kb_id: int) -> None:
    """删除 kb_{id} collection；不存在时静默容忍。M3 接通真实实现。"""
    logger.info("delete_collection 占位 kb_id=%s（M3 接通）", kb_id)
