"""文档解析：txt/md（utf-8）、pdf（pypdf）、docx（python-docx）；解析为空抛业务异常。"""

from __future__ import annotations

from pathlib import Path


class ParserError(Exception):
    """解析失败或内容为空（业务异常，ingest 捕获写入 error_msg）。"""


def _parse_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ParserError(f"文本编码不是 UTF-8: {exc}") from exc


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def _parse_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    # 表格内容一并提取
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


_PARSERS = {
    "txt": _parse_text,
    "md": _parse_text,
    "pdf": _parse_pdf,
    "docx": _parse_docx,
}


def parse_file(path: Path | str, file_type: str) -> str:
    path = Path(path)
    if not path.exists():
        raise ParserError(f"文件不存在: {path}")
    parser = _PARSERS.get(file_type.lower())
    if parser is None:
        raise ParserError(f"不支持的文件类型: {file_type}")
    try:
        text = parser(path)
    except ParserError:
        raise
    except Exception as exc:  # noqa: BLE001  统一转业务异常
        raise ParserError(f"解析失败: {exc}") from exc
    if not text.strip():
        raise ParserError("解析内容为空")
    return text
