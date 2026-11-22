"""种子数据脚本（幂等）：双账号 + 按 seed_docs 一级子文件夹建三库 + 12 份文档。

- admin/admin123、user/user123
- 同 kb 同 filename 已存在则跳过
- 文档复制到 uploads/{stored_name}，M1 阶段 status=pending（M3 接通向量化）
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Document, KbMember, KnowledgeBase, User  # noqa: E402

SEED_DOCS = ROOT / "seed_docs"
ALLOWED = {"txt", "pdf", "md", "docx"}


def get_or_create_user(db, username: str, password: str, role: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            nickname=username,
            role=role,
            status=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[user] 创建 {username} ({role})")
    else:
        print(f"[user] 已存在 {username}")
    return user


def get_or_create_kb(db, name: str, created_by: int) -> KnowledgeBase:
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == name))
    if kb is None:
        kb = KnowledgeBase(name=name, description=f"种子知识库：{name}", created_by=created_by)
        db.add(kb)
        db.commit()
        db.refresh(kb)
        print(f"[kb] 创建 {name} (id={kb.id})")
    else:
        print(f"[kb] 已存在 {name} (id={kb.id})")
    return kb


def ensure_member(db, kb_id: int, user_id: int) -> None:
    exists = db.scalar(
        select(KbMember).where(KbMember.kb_id == kb_id, KbMember.user_id == user_id)
    )
    if exists is None:
        db.add(KbMember(kb_id=kb_id, user_id=user_id))
        db.commit()
        print(f"[member] user={user_id} -> kb={kb_id}")


def seed_document(db, kb: KnowledgeBase, src: Path, created_by: int) -> None:
    filename = src.name
    exists = db.scalar(
        select(Document).where(Document.kb_id == kb.id, Document.filename == filename)
    )
    if exists is not None:
        print(f"[doc] 跳过（已存在） {kb.name}/{filename}")
        return

    ext = src.suffix.lstrip(".").lower()
    if ext not in ALLOWED:
        print(f"[doc] 跳过（类型不允许） {filename}")
        return

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, upload_root / stored_name)

    doc = Document(
        kb_id=kb.id,
        filename=filename,
        stored_name=stored_name,
        file_type=ext,
        file_size=src.stat().st_size,
        status="pending",
        created_by=created_by,
    )
    db.add(doc)
    db.commit()
    print(f"[doc] 入库 {kb.name}/{filename} -> {stored_name} (pending)")


def main() -> None:
    if not SEED_DOCS.is_dir():
        raise SystemExit(f"seed_docs 不存在: {SEED_DOCS}")

    db = SessionLocal()
    try:
        admin = get_or_create_user(db, "admin", "admin123", "admin")
        user = get_or_create_user(db, "user", "user123", "user")

        folders = sorted(
            [p for p in SEED_DOCS.iterdir() if p.is_dir()],
            key=lambda p: p.name,
        )
        if not folders:
            raise SystemExit("seed_docs 下没有子文件夹")

        total_docs = 0
        for folder in folders:
            kb = get_or_create_kb(db, folder.name, created_by=admin.id)
            ensure_member(db, kb.id, admin.id)
            ensure_member(db, kb.id, user.id)
            for src in sorted(folder.rglob("*")):
                if src.is_file() and src.suffix.lstrip(".").lower() in ALLOWED:
                    seed_document(db, kb, src, created_by=admin.id)
                    total_docs += 1

        print(f"完成：{len(folders)} 个知识库，{total_docs} 份文档候选")
    finally:
        db.close()


if __name__ == "__main__":
    main()
