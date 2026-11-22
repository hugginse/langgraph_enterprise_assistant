"""Anthropic Claude LLM 流式通道（thinking content block → thinking 事件）。"""

from __future__ import annotations

from typing import Iterator

import anthropic

from app.core.config import Settings
from app.services.llm.base import ConfigError


class AnthropicChatStreamer:
    def __init__(self, cfg: Settings) -> None:
        if not cfg.anthropic_api_key:
            raise ConfigError("LLM_PROVIDER=anthropic 但 ANTHROPIC_API_KEY 为空")
        self._cfg = cfg
        self._client = anthropic.Anthropic(
            api_key=cfg.anthropic_api_key,
            base_url=cfg.anthropic_base_url or None,
            timeout=cfg.llm_timeout_seconds,
            max_retries=cfg.llm_max_retries,
        )

    @property
    def fingerprint(self) -> str:
        return f"anthropic/{self._cfg.anthropic_model}"

    def stream(self, *, system: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        with self._client.messages.stream(
            model=self._cfg.anthropic_model,
            max_tokens=self._cfg.anthropic_max_tokens,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        yield "thinking", delta.thinking
                    elif delta.type == "text_delta":
                        yield "delta", delta.text
