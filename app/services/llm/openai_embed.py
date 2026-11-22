"""OpenAI 兼容 Embedding 通道。"""

from __future__ import annotations

from openai import OpenAI

from app.core.config import Settings
from app.services.llm.base import ConfigError


class OpenAIEmbedder:
    def __init__(self, cfg: Settings) -> None:
        if not cfg.effective_embed_api_key:
            raise ConfigError("EMBED_PROVIDER=openai 但 EMBED_API_KEY / OPENAI_API_KEY 为空")
        self._cfg = cfg
        self._client = OpenAI(
            api_key=cfg.effective_embed_api_key,
            base_url=cfg.effective_embed_base_url or None,
            timeout=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )

    @property
    def fingerprint(self) -> str:
        return f"openai/{self._cfg.effective_embed_model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embeddings.create(
            model=self._cfg.effective_embed_model, input=texts
        )
        return [list(item.embedding) for item in sorted(result.data, key=lambda d: d.index)]
