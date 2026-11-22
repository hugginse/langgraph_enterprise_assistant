"""分块：递归分隔符（\\n\\n → \\n → 。 → 字符滑窗），500/50，产出 chunk_index。"""

from __future__ import annotations

_SEPARATORS = ["\n\n", "\n", "。"]


def _split_by(text: str, sep: str, size: int) -> list[str]:
    if sep not in text:
        return [text]
    parts: list[str] = []
    buf = ""
    for piece in text.split(sep):
        candidate = piece if not buf else buf + sep + piece
        if len(candidate) <= size:
            buf = candidate
        else:
            if buf:
                parts.append(buf)
            buf = piece
    if buf:
        parts.append(buf)
    return parts


def _slide(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def _recursive(text: str, size: int, overlap: int, seps: list[str]) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    if not seps:
        return _slide(text, size, overlap)
    sep, rest = seps[0], seps[1:]
    pieces = _split_by(text, sep, size)
    out: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= size:
            out.append(piece)
        else:
            out.extend(_recursive(piece, size, overlap, rest))
    return out


def chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """递归分块；overlap 保证滑窗上下文衔接。返回非空块列表。"""
    if size <= 0:
        raise ValueError("chunk size 必须为正")
    overlap = max(0, min(overlap, size - 1))
    return _recursive(text, size, overlap, list(_SEPARATORS))
