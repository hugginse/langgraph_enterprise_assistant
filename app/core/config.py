"""Pydantic Settings：安全 / 数据库 / 双通道模型 / 检索与存储配置。

双通道约束（见 docs/architecture.md §4）：
- LLM_PROVIDER ∈ {ollama, openai, anthropic}
- EMBED_PROVIDER ∈ {ollama, openai}（Anthropic 无官方 embeddings）
- 指向 API 通道但缺 key → 显式失败，禁止静默降级到本地 Ollama
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 安全与数据库 ----------
    secret_key: str = "dev-secret-key-change-me"
    jwt_expire_hours: int = 24
    database_url: str = (
        "postgresql+psycopg2://rag:rag123@localhost:5432/langgraph_enterprise"
    )

    # ---------- LLM 通道 ----------
    llm_provider: Literal["ollama", "openai", "anthropic"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen3:4b"
    ollama_think: bool = True
    ollama_num_ctx: int = 8192
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_max_tokens: int = 4096
    anthropic_base_url: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    # ---------- Embedding 通道 ----------
    embed_provider: Literal["ollama", "openai"] = "ollama"
    ollama_embed_model: str = "qwen3-embedding:4b"
    ollama_embed_num_ctx: int = 4096
    embed_api_key: str = ""
    embed_base_url: str = ""
    embed_model: str = ""

    # ---------- 检索 / 分块 / 存储 / 图 ----------
    retrieval_top_k: int = 4
    retrieval_score_threshold: float = 0.3
    chunk_size: int = 500
    chunk_overlap: int = 50
    chroma_persist_dir: str = "chroma_data"
    upload_dir: str = "uploads"
    upload_max_mb: int = 50
    ingest_on_upload: bool = True  # 测试/CI 置 false，避免依赖 Ollama
    max_rewrite_attempts: int = Field(default=2, ge=1, le=5)
    grade_with_llm: bool = False
    enable_node_sse: bool = True
    checkpoint_enabled: bool = True
    checkpoint_table: str = "langgraph_checkpoints"

    # ---------- 显式缺 key 校验 ----------
    @model_validator(mode="after")
    def _validate_provider_keys(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER=openai 但 OPENAI_API_KEY 为空：禁止静默降级到 Ollama"
            )
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "LLM_PROVIDER=anthropic 但 ANTHROPIC_API_KEY 为空：禁止静默降级到 Ollama"
            )
        if self.embed_provider == "openai" and not (
            self.embed_api_key or self.openai_api_key
        ):
            raise ValueError(
                "EMBED_PROVIDER=openai 但 EMBED_API_KEY / OPENAI_API_KEY 均为空："
                "禁止静默降级到 Ollama"
            )
        return self

    @property
    def effective_embed_api_key(self) -> str:
        return self.embed_api_key or self.openai_api_key

    @property
    def effective_embed_base_url(self) -> str:
        return self.embed_base_url or self.openai_base_url

    @property
    def effective_embed_model(self) -> str:
        return self.embed_model or "text-embedding-3-small"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
