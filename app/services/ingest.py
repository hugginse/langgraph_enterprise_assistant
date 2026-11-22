"""文档异步入库：pending → processing → completed|failed；失败写 error_msg。

启动时清理遗留死状态（pending/processing → failed）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select, update

from app.core.config import settings
from app.db import SessionLocal
from app.models import Document, EmbedIndexMeta
from app.services import vector
from app.services.chunker import chunk_text
from app.services.parser import ParserError, parse_file

logger = logging.getLogger(__name__)


def cleanup_dead_statuses() -> int:
    """应用启动清理：上次进程遗留的 pending/processing → failed。"""
    db = SessionLocal()
    try:
        result = db.execute(
            update(Document)
            .where(Document.status.in_(["pending", "processing"]))
            .values(status="failed", error_msg="应用重启时该文档处于处理中，已标记失败，请重新上传")
        )
        db.commit()
        count = result.rowcount or 0
        if count:
            logger.warning("清理遗留死状态文档 %s 份", count)
        return count
    finally:
        db.close()


def ingest_document(doc_id: int) -> None:
    """BackgroundTasks 入口：解析 → 分块 → 向量化 → 写 Chroma + 状态推进。"""
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        doc.status = "processing"
        doc.error_msg = ""
        db.commit()

        path = Path(settings.upload_dir) / doc.stored_name
        text = parse_file(path, doc.file_type)
        chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise ParserError("分块结果为空")

        from app.services.llm import create_embedder

        embedder = create_embedder()
        vectors = embedder.embed(chunks)
        vector.add_chunks(
            kb_id=doc.kb_id,
            doc_id=doc.id,
            file_name=doc.filename,
            chunks=chunks,
            embeddings=vectors,
            fingerprint=embedder.fingerprint,
            db=db,
        )

        doc.status = "completed"
        doc.chunk_count = len(chunks)
        doc.error_msg = ""
        db.commit()
        logger.info("入库完成 doc=%s chunks=%s", doc.id, len(chunks))
    except Exception as exc:  # noqa: BLE001  失败写 error_msg，不抛给调用方
        db.rollback()
        logger.exception("入库失败 doc=%s", doc_id)
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.error_msg = str(exc)[:2000]
            db.commit()
    finally:
        db.close()


def reindex_kb(kb_id: int) -> None:
    """换 Embed 模型后全量重建：清空该库向量 → 逐文档重新入库。"""
    vector.clear_collection(kb_id)
    db = SessionLocal()
    try:
        doc_ids = list(
            db.scalars(
                select(Document.id).where(Document.kb_id == kb_id).order_by(Document.id)
            ).all()
        )
        meta = db.get(EmbedIndexMeta, kb_id)
        if meta is not None:
            db.delete(meta)
            db.commit()
    finally:
        db.close()
    for doc_id in doc_ids:
        ingest_document(doc_id)
