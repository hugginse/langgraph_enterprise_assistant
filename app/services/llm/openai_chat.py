"""OpenAI 兼容 LLM 流式通道。"""

from __future__ import annotations

from typing import Iterator

from openai import OpenAI

from app.core.config import Settings
from app.services.llm.base import ConfigError


class OpenAIChatStreamer:
    def __init__(self, cfg: Settings) -> None:
        if not cfg.openai_api_key:
            raise ConfigError("LLM_PROVIDER=openai 但 OPENAI_API_KEY 为空")
        self._cfg = cfg
        self._client = OpenAI(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            timeout=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )

    @property
    def fingerprint(self) -> str:
        return f"openai/{self._cfg.openai_model}"

    def stream(self, *, system: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        full = [{"role": "system", "content": system}, *messages]
        stream = self._client.chat.completions.create(
            model=self._cfg.openai_model,
            messages=full,  # type: ignore[arg-type]
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield "thinking", reasoning
            if delta.content:
                yield "delta", delta.content
