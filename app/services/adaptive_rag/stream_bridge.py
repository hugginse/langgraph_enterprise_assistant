"""generate 内 token → 回调桥（architecture §6.2）。

禁止 invoke 整段后再切片：chat_model.stream 逐块转发给 on_token。
"""

from __future__ import annotations

from typing import Any, Callable

TokenCallback = Callable[[str, str], None]  # ("thinking" | "delta", text)


def get_callback(config: Any, key: str) -> Callable | None:
    """从 LangGraph config.configurable 取回调（每请求注入）。"""
    if config is None:
        return None
    configurable = config.get("configurable") if isinstance(config, dict) else None
    if not configurable:
        return None
    cb = configurable.get(key)
    return cb if callable(cb) else None


def stream_with_callback(
    chat_model: Any,
    *,
    system: str,
    messages: list[dict],
    on_token: TokenCallback | None = None,
) -> str:
    """逐块转发 thinking/delta，返回拼接后的 delta 文本（thinking 不计入）。"""
    parts: list[str] = []
    for kind, text in chat_model.stream(system=system, messages=messages):
        if on_token is not None:
            on_token(kind, text)
        if kind == "delta":
            parts.append(text)
    return "".join(parts)


def complete(chat_model: Any, *, system: str, messages: list[dict]) -> str:
    """非流式便捷方法（rewrite / grade 用）：只拼接 delta。"""
    return stream_with_callback(chat_model, system=system, messages=messages, on_token=None)
