"""Ollama LLM 流式通道（默认本地 qwen3:4b）。"""

from __future__ import annotations

from typing import Iterator

import ollama

from app.core.config import Settings


class OllamaChatStreamer:
    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg
        self._client = ollama.Client(host=cfg.ollama_base_url)

    @property
    def fingerprint(self) -> str:
        return f"ollama/{self._cfg.ollama_llm_model}"

    def stream(self, *, system: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        # 强制 think + num_ctx：防 16GB 显存被 KV cache 挤爆（见 CLAUDE.md 环境铁律）
        options: dict = {
            "num_ctx": self._cfg.ollama_num_ctx,
            "think": self._cfg.ollama_think,
        }
        response = self._client.chat(
            model=self._cfg.ollama_llm_model,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
            options=options,
        )
        for chunk in response:
            msg = chunk.get("message") or {}
            thinking = msg.get("thinking") or ""
            if thinking:
                yield "thinking", thinking
            content = msg.get("content") or ""
            if content:
                yield "delta", content
