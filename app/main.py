"""FastAPI 应用工厂与健康检查。"""

from fastapi import FastAPI

from app.middleware import RequestIDMiddleware, setup_logging


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="langgraph_enterprise_assistant",
        description="企业级知识库问答系统（LangGraph Adaptive RAG）",
        version="0.1.0",
    )
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
