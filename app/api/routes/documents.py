"""文档上传、列表与删除（M3：BackgroundTasks 异步向量化）。

类型白名单 txt/pdf/md/docx；50MB 限制；uuid stored_name 落盘 uploads/{stored_name}。
状态机：pending → processing → completed|failed（失败写 error_msg）。
"""

import logging
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.knowledge_bases import require_kb_access
from app.core.config import settings
from app.core.security import login_required
from app.db import get_db
from app.models import Document, User
from app.schemas.document import DocumentOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["documents"])

ALLOWED_TYPES = {"txt", "pdf", "md", "docx"}


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> DocumentOut:
    require_kb_access(user, db, kb_id)

    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400, detail=f"不支持的文件类型，仅允许 {sorted(ALLOWED_TYPES)}"
        )

    content = await file.read()
    max_bytes = settings.upload_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"文件超过 {settings.upload_max_mb}MB 限制")
    if not content:
        raise HTTPException(status_code=400, detail="空文件")

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    (upload_root / stored_name).write_bytes(content)

    doc = Document(
        kb_id=kb_id,
        filename=filename,
        stored_name=stored_name,
        file_type=ext,
        file_size=len(content),
        status="pending",
        created_by=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    if settings.ingest_on_upload:
        from app.services.ingest import ingest_document  # noqa: PLC0415

        background_tasks.add_task(ingest_document, doc.id)
    return DocumentOut.model_validate(doc)


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
def list_documents(
    kb_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    require_kb_access(user, db, kb_id)
    rows = db.scalars(
        select(Document).where(Document.kb_id == kb_id).order_by(Document.id.desc())
    ).all()
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(
    doc_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = db.scalar(select(Document).where(Document.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_access(user, db, doc.kb_id)
    return DocumentOut.model_validate(doc)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    user: User = Depends(login_required),
    db: Session = Depends(get_db),
) -> Response:
    doc = db.scalar(select(Document).where(Document.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_access(user, db, doc.kb_id)

    path = Path(settings.upload_dir) / doc.stored_name
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("删除上传文件失败 %s: %s", path, exc)

    # Chroma 分块清理（不存在时容忍）
    from app.services import vector  # noqa: PLC0415

    try:
        vector.delete_doc(doc.kb_id, doc.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chroma 分块清理失败 doc=%s: %s", doc_id, exc)

    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
