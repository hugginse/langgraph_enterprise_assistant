"""LLM/Embed 双通道工厂单测：三分支、两 embed 分支、缺 key 显式失败。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.llm import ConfigError, create_chat_streamer, create_embedder
from app.services.llm.anthropic_chat import AnthropicChatStreamer
from app.services.llm.ollama_chat import OllamaChatStreamer
from app.services.llm.ollama_embed import OllamaEmbedder
from app.services.llm.openai_chat import OpenAIChatStreamer
from app.services.llm.openai_embed import OpenAIEmbedder


def _base(**over) -> Settings:
    defaults = dict(
        llm_provider="ollama",
        embed_provider="ollama",
        openai_api_key="",
        anthropic_api_key="",
        embed_api_key="",
    )
    defaults.update(over)
    return Settings(**defaults)


# ---------- 工厂分支 ----------


def test_factory_default_ollama():
    cfg = _base()
    assert isinstance(create_chat_streamer(cfg), OllamaChatStreamer)
    assert isinstance(create_embedder(cfg), OllamaEmbedder)


def test_factory_openai_branch():
    cfg = _base(llm_provider="openai", openai_api_key="sk-test", embed_provider="openai",
                embed_api_key="sk-test")
    assert isinstance(create_chat_streamer(cfg), OpenAIChatStreamer)
    assert isinstance(create_embedder(cfg), OpenAIEmbedder)


def test_factory_anthropic_branch():
    cfg = _base(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    assert isinstance(create_chat_streamer(cfg), AnthropicChatStreamer)


def test_embed_provider_has_no_anthropic():
    _base()
    # EMBED_PROVIDER 类型上不存在 anthropic
    with pytest.raises(ValidationError):
        _base(embed_provider="anthropic")


# ---------- 缺 key 显式失败（禁止静默降级） ----------


def test_openai_llm_missing_key_config_fail():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        _base(llm_provider="openai", openai_api_key="")


def test_anthropic_llm_missing_key_config_fail():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        _base(llm_provider="anthropic", anthropic_api_key="")


def test_openai_embed_missing_key_config_fail():
    with pytest.raises(ValidationError, match="EMBED"):
        _base(embed_provider="openai", embed_api_key="", openai_api_key="")


def test_openai_streamer_constructor_raises_without_key():
    """绕过 Settings 校验直接构造实现类时也必须显式失败。"""
    cfg = Settings.model_construct(
        openai_api_key="", llm_provider="openai", llm_timeout_seconds=30, llm_max_retries=3
    )
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAIChatStreamer(cfg)


def test_anthropic_streamer_constructor_raises_without_key():
    cfg = Settings.model_construct(anthropic_api_key="", anthropic_max_tokens=4096)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicChatStreamer(cfg)


# ---------- fingerprint（embed 指纹校验的基础） ----------


def test_fingerprints():
    cfg = _base()
    assert create_chat_streamer(cfg).fingerprint == "ollama/qwen3:4b"
    assert create_embedder(cfg).fingerprint == "ollama/qwen3-embedding:4b"

    cfg2 = _base(embed_provider="openai", embed_api_key="k", embed_model="")
    assert create_embedder(cfg2).fingerprint == "openai/text-embedding-3-small"
