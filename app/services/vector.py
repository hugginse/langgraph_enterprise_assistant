"""Chroma 向量库封装：add_chunks / delete_doc / delete_collection / search。

约束（architecture §9）：
- 建 collection 必须 metadata={"hnsw:space":"cosine"}（relevance = 1 - distance）
- 分块 id：doc_{doc_id}_chunk_{i}；metadata：doc_id / file_name / chunk_index
- 写入时校验并更新 embed_index_meta（指纹 + dimension 双写）
- 检索前指纹校验：不一致 → EmbeddingMismatchError（路由层转 409）
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models import EmbedIndexMeta

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CLIENT: Any = None


class EmbeddingMismatchError(Exception):
    """当前 Embedder.fingerprint 与索引指纹不一致（embedding_mismatch）。"""


def verify_fingerprint(index_fingerprint: str, current_fingerprint: str) -> None:
    """检索前校验：不一致必须显式报错，禁止静默用错向量。"""
    if index_fingerprint and current_fingerprint and index_fingerprint != current_fingerprint:
        raise EmbeddingMismatchError(
            f"embedding_mismatch: 索引={index_fingerprint} 当前={current_fingerprint}，"
            "请执行 POST /knowledge-bases/{{id}}/reindex 重建向量"
        )


def get_client():
    """进程内单例 PersistentClient（persist_directory = CHROMA_PERSIST_DIR）。"""
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            import chromadb

            _CLIENT = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        return _CLIENT


def collection_name(kb_id: int) -> str:
    return f"kb_{kb_id}"


def get_or_create_collection(kb_id: int):
    """必须显式 cosine 空间——分数阈值语义依赖它。"""
    client = get_client()
    return client.get_or_create_collection(
        name=collection_name(kb_id),
        metadata={"hnsw:space": "cosine"},
    )


def _load_meta(db: Session, kb_id: int) -> EmbedIndexMeta | None:
    return db.get(EmbedIndexMeta, kb_id)


def check_index_fingerprint(db: Session, kb_id: int, current_fingerprint: str) -> None:
    """检索前调用；索引不存在时跳过（空库允许首检）。"""
    meta = _load_meta(db, kb_id)
    if meta is None:
        return
    verify_fingerprint(meta.embed_fingerprint, current_fingerprint)


def add_chunks(
    kb_id: int,
    doc_id: int,
    file_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    fingerprint: str,
    db: Session | None = None,
) -> None:
    """写入分块并双写 embed_index_meta；同一 kb 指纹不一致拒绝（须先 reindex）。"""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks 与 embeddings 数量不一致")
    if not chunks:
        return
    own_session = db is None
    db = db or SessionLocal()
    try:
        meta = _load_meta(db, kb_id)
        if meta is not None and meta.embed_fingerprint != fingerprint:
            raise EmbeddingMismatchError(
                f"embedding_mismatch: kb={kb_id} 索引={meta.embed_fingerprint} "
                f"当前={fingerprint}，请先 reindex"
            )
        collection = get_or_create_collection(kb_id)
        ids = [f"doc_{doc_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {"doc_id": doc_id, "file_name": file_name, "chunk_index": i}
            for i in range(len(chunks))
        ]
        # 同 id 覆盖（重复入库/重传场景）
        collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        if meta is None:
            meta = EmbedIndexMeta(
                kb_id=kb_id, embed_fingerprint=fingerprint, dimension=len(embeddings[0])
            )
            db.add(meta)
        else:
            meta.embed_fingerprint = fingerprint
            meta.dimension = len(embeddings[0])
        db.commit()
    finally:
        if own_session:
            db.close()


def delete_doc(kb_id: int, doc_id: int) -> None:
    """删除某文档全部分块；collection 不存在时容忍。"""
    client = get_client()
    try:
        collection = client.get_collection(collection_name(kb_id))
    except Exception:  # noqa: BLE001  不存在即视为已清理
        return
    collection.delete(where={"doc_id": doc_id})


def delete_collection(kb_id: int) -> None:
    """删除 kb_{id} collection；不存在时静默容忍。"""
    client = get_client()
    try:
        client.delete_collection(collection_name(kb_id))
    except Exception:  # noqa: BLE001
        logger.info("collection 不存在，跳过删除 kb_id=%s", kb_id)


def clear_collection(kb_id: int) -> None:
    """reindex 前清空（删除重建同名 collection）。"""
    delete_collection(kb_id)


def search(
    query: str,
    *,
    kb_id: int,
    top_k: int | None = None,
    embedder: Any = None,
    db: Session | None = None,
    skip_fingerprint_check: bool = False,
) -> list[dict]:
    """向量检索：返回 [{doc_id, file_name, chunk_index, score, text}]。

    score = 1 - cosine distance；检索前做指纹校验。
    """
    top_k = top_k or settings.retrieval_top_k
    own_session = db is None
    db = db or SessionLocal()
    try:
        if embedder is None:
            from app.services.llm import create_embedder

            embedder = create_embedder()
        if not skip_fingerprint_check:
            check_index_fingerprint(db, kb_id, embedder.fingerprint)

        client = get_client()
        try:
            collection = client.get_collection(collection_name(kb_id))
        except Exception:  # noqa: BLE001  未建索引 → 零命中
            return []
        if collection.count() == 0:
            return []

        query_vec = embedder.embed([query])[0]
        res = collection.query(
            query_embeddings=[query_vec],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        out: list[dict] = []
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for text, meta, dist in zip(docs, metas, dists, strict=False):
            out.append(
                {
                    "doc_id": (meta or {}).get("doc_id"),
                    "file_name": (meta or {}).get("file_name", ""),
                    "chunk_index": (meta or {}).get("chunk_index", 0),
                    "score": round(1.0 - float(dist), 6),
                    "text": text or "",
                }
            )
        return out
    finally:
        if own_session:
            db.close()


def default_retriever(query: str, *, kb_id: int, top_k: int = 4) -> list[dict]:
    """图 retrieve 节点的默认检索器（错误上抛由节点捕获进 errors）。"""
    return search(query, kb_id=kb_id, top_k=top_k)


def get_index_meta(db: Session, kb_id: int) -> EmbedIndexMeta | None:
    return db.scalar(select(EmbedIndexMeta).where(EmbedIndexMeta.kb_id == kb_id))
