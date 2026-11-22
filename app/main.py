"""FastAPI 应用工厂、健康检查与 lifespan（死状态清理）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import (
    auth,
    chat,
    documents,
    feedback,
    knowledge_bases,
    retrieval,
    stats,
    users,
)
from app.middleware import RequestIDMiddleware, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.services.ingest import cleanup_dead_statuses

    cleanup_dead_statuses()
    yield


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="langgraph_enterprise_assistant",
        description="企业级知识库问答系统（LangGraph Adaptive RAG）",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIDMiddleware)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(knowledge_bases.router)
    app.include_router(documents.router)
    app.include_router(stats.router)
    app.include_router(chat.router)
    app.include_router(feedback.router)
    app.include_router(retrieval.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
