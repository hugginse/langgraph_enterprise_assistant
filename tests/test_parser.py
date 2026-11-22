"""四格式解析与分块单测（fixture 使用 seed_docs 真实文件）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chunker import chunk_text
from app.services.parser import ParserError, parse_file

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed_docs"


def _find(ext: str) -> Path:
    for p in sorted(SEED.rglob(f"*.{ext}")):
        return p
    raise AssertionError(f"seed_docs 缺少 .{ext} 文件")


@pytest.mark.parametrize("ext", ["txt", "md", "pdf", "docx"])
def test_parse_four_formats(ext: str):
    path = _find(ext)
    text = parse_file(path, ext)
    assert text.strip(), f"{path.name} 解析为空"
    assert len(text) > 100


def test_parse_unsupported_type():
    with pytest.raises(ParserError, match="不支持"):
        parse_file(_find("txt"), "xlsx")


def test_parse_missing_file():
    with pytest.raises(ParserError, match="不存在"):
        parse_file(SEED / "no-such-file.txt", "txt")


def test_parse_empty_content(tmp_path: Path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(ParserError, match="为空"):
        parse_file(empty, "txt")


def test_chunker_size_and_overlap():
    text = "第一段内容。\n\n" + ("员工请假需提前申请。" * 80)
    chunks = chunk_text(text, size=200, overlap=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_chunker_small_text_single_chunk():
    chunks = chunk_text("短文本", size=500, overlap=50)
    assert chunks == ["短文本"]


def test_chunker_seed_doc_covers_content():
    text = parse_file(_find("md"), "md")
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) >= 2
    joined = "".join(chunks)
    # 滑窗/分块后首尾内容仍在
    assert text.strip()[:20] in joined
