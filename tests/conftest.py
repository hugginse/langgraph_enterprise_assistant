"""pytest 共享夹具：独立测试库、应用工厂、用户/权限辅助。

必须在导入 app.* 之前设置环境变量（app.core.config 在导入时缓存 Settings）。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# ---- 环境先于任何 app 导入 ----
ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = (
    "postgresql+psycopg2://rag:rag123@localhost:5432/langgraph_enterprise_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CHECKPOINT_ENABLED"] = "false"
os.environ["CHROMA_PERSIST_DIR"] = str(ROOT / "chroma_data_test")
os.environ["UPLOAD_DIR"] = str(ROOT / "uploads_test")
os.environ["INGEST_ON_UPLOAD"] = "false"  # 测试不依赖 Ollama 向量化

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import KbMember, KnowledgeBase, User  # noqa: E402

get_settings.cache_clear()

engine = create_engine(TEST_DATABASE_URL, future=True)

TABLES = (
    "chat_feedback, chat_messages, chat_sessions, embed_index_meta, "
    "documents, kb_members, knowledge_bases, users"
)


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db() -> Iterator[None]:
    """测试库建表（Alembic 全量迁移；表结构变更后自动升级）。"""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _reset_graph() -> Iterator[None]:
    from app.services.rag_runtime import reset_graph

    reset_graph()
    yield
    reset_graph()


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def db() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def make_user(
    db,
    username: str = "tester",
    password: str = "pass1234",
    role: str = "user",
    status: int = 1,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        nickname=username,
        role=role,
        status=status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def make_kb(db, name: str = "测试库", created_by: int | None = None) -> KnowledgeBase:
    kb = KnowledgeBase(name=name, description="", status=1, created_by=created_by)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def add_member(db, kb_id: int, user_id: int) -> KbMember:
    member = KbMember(kb_id=kb_id, user_id=user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


class ScriptedChatModel:
    """按脚本分块 yield 的 ChatModel 替身（真流式单测用）。"""

    def __init__(self, chunks: list[tuple[str, str]] | None = None, *, fail: bool = False):
        self.chunks = chunks if chunks is not None else [("delta", "默认回答")]
        self.fail = fail
        self.calls: list[dict] = []

    def stream(self, *, system: str, messages: list[dict]):
        self.calls.append({"system": system, "messages": messages})
        if self.fail:
            raise RuntimeError("scripted failure")
        yield from self.chunks

    @property
    def fingerprint(self) -> str:
        return "scripted/v1"


class DeterministicFakeEmbeddings:
    """可复现的确定性假向量（同文本恒同向量）。"""

    def __init__(self, dim: int = 8, fingerprint: str = "fake/deterministic-v1"):
        self.dim = dim
        self._fp = fingerprint

    @property
    def fingerprint(self) -> str:
        return self._fp

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        out: list[list[float]] = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            out.append(
                [((digest[i % len(digest)] / 255.0) - 0.5) for i in range(self.dim)]
            )
        return out
