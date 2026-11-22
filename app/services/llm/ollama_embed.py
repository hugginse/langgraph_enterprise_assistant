"""Ollama Embedding 通道（默认本地 qwen3-embedding:4b，num_ctx 固定 4096）。"""

from __future__ import annotations

import ollama

from app.core.config import Settings


class OllamaEmbedder:
    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg
        self._client = ollama.Client(host=cfg.ollama_base_url)

    @property
    def fingerprint(self) -> str:
        return f"ollama/{self._cfg.ollama_embed_model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(
            model=self._cfg.ollama_embed_model,
            input=texts,
            options={"num_ctx": self._cfg.ollama_embed_num_ctx},
        )
        return [list(v) for v in result["embeddings"]]
