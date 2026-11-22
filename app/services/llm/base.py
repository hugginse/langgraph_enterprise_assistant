"""ChatStreamer / Embedder Protocol 与双通道工厂。

约束（architecture §6）：
- ChatStreamer.stream 逐块 yield ("thinking" | "delta", text)，禁止整段返回后切片
- Embedder.fingerprint 用于索引校验（如 'ollama/qwen3-embedding:4b'）
- 缺 key 显式抛 ConfigError，禁止静默降级
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from app.core.config import Settings, settings


class ConfigError(RuntimeError):
    """通道配置错误（缺 key / 未知 provider）。"""


@runtime_checkable
class ChatStreamer(Protocol):
    def stream(self, *, system: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        """yield ("thinking" | "delta", text)。"""
        ...


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def fingerprint(self) -> str:
        """如 'ollama/qwen3-embedding:4b' 或 'openai/text-embedding-3-small'。"""
        ...


def create_chat_streamer(cfg: Settings | None = None) -> ChatStreamer:
    cfg = cfg or settings
    if cfg.llm_provider == "ollama":
        from app.services.llm.ollama_chat import OllamaChatStreamer

        return OllamaChatStreamer(cfg)
    if cfg.llm_provider == "openai":
        from app.services.llm.openai_chat import OpenAIChatStreamer

        return OpenAIChatStreamer(cfg)
    if cfg.llm_provider == "anthropic":
        from app.services.llm.anthropic_chat import AnthropicChatStreamer

        return AnthropicChatStreamer(cfg)
    raise ConfigError(f"未知 LLM_PROVIDER: {cfg.llm_provider}")


def create_embedder(cfg: Settings | None = None) -> Embedder:
    cfg = cfg or settings
    if cfg.embed_provider == "ollama":
        from app.services.llm.ollama_embed import OllamaEmbedder

        return OllamaEmbedder(cfg)
    if cfg.embed_provider == "openai":
        from app.services.llm.openai_embed import OpenAIEmbedder

        return OpenAIEmbedder(cfg)
    raise ConfigError(f"未知 EMBED_PROVIDER: {cfg.embed_provider}（Anthropic 无官方 embeddings）")
