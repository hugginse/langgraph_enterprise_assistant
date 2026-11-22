# langgraph_enterprise_assistant API 镜像
FROM ghcr.io/astral-sh/uv:0.9-slim AS uv-bin

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# 依赖层缓存：先只拷清单
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# 应用代码
COPY app/ ./app/
COPY static/ ./static/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
COPY docker/ ./docker/
RUN uv sync --frozen --no-dev

# 非 root 运行
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/uploads /app/chroma_data /app/checkpoints \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
