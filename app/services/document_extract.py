"""Knowledge document extraction & chunking.

Turns an uploaded file (txt / md / pdf / doc / docx) into plain text and splits
it into retrieval-friendly chunks. Parsing libraries (pypdf, pdfplumber,
docx2txt) are optional at import time so a missing dependency degrades to a
clear error for that format only, rather than breaking the whole module.
"""
from __future__ import annotations

import io
from pathlib import Path

# Extensions we accept for knowledge ingestion.
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".doc", ".docx"}

# Hard cap on a single upload (10 MB). Mirrors a typical enterprise document.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Target characters per chunk and the minimum size for a trailing chunk to
# stand on its own (smaller tails are merged into the previous chunk).
CHUNK_TARGET_CHARS = 1200
CHUNK_MIN_TAIL_CHARS = 200


class DocumentExtractionError(ValueError):
    """Raised when an upload cannot be parsed into usable text."""


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from a file's bytes, dispatched by extension."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise DocumentExtractionError(
            f"不支持的文件格式：{suffix or '未知'}。支持 txt、md、pdf、doc、docx。"
        )
    if not data:
        raise DocumentExtractionError("文件内容为空。")

    if suffix in {".txt", ".md", ".markdown"}:
        text = _decode_text(data)
    elif suffix == ".pdf":
        text = _extract_pdf(data)
    else:  # .doc / .docx
        text = _extract_docx(data, suffix)

    text = _normalize(text)
    if not text:
        raise DocumentExtractionError("未能从文件中解析出文本内容。")
    return text


def _decode_text(data: bytes) -> str:
    """Decode raw bytes, trying common encodings before a lossy fallback."""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    """Extract text from a PDF, preferring pdfplumber, falling back to pypdf."""
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    except DocumentExtractionError:
        raise
    except Exception:
        pass  # fall through to pypdf

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        raise DocumentExtractionError(f"PDF 解析失败：{exc}") from exc


def _extract_docx(data: bytes, suffix: str) -> str:
    """Extract text from a Word document via docx2txt (.docx only)."""
    if suffix == ".doc":
        raise DocumentExtractionError(
            "暂不支持旧版 .doc 二进制格式，请另存为 .docx 后再上传。"
        )
    try:
        import docx2txt
    except ImportError as exc:
        raise DocumentExtractionError("缺少 docx2txt 依赖，无法解析 Word 文档。") from exc

    import os
    import tempfile

    # docx2txt reads from a path, so spill to a temp file and clean it up.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return docx2txt.process(tmp_path) or ""
    except Exception as exc:  # noqa: BLE001
        raise DocumentExtractionError(f"Word 文档解析失败：{exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _normalize(text: str) -> str:
    """Collapse excess blank lines and trailing whitespace."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line:
            blank_run = 0
            cleaned.append(line)
        else:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip()


def chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Split text into chunks of ~target_chars, preferring paragraph breaks.

    Paragraphs are accumulated until adding the next one would exceed the
    target; a single paragraph longer than the target is hard-split. A short
    trailing chunk is merged back into the previous one to avoid tiny fragments.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > target_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), target_chars):
                chunks.append(para[i : i + target_chars])
            continue
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= target_chars:
            current = f"{current}\n\n{para}"
        else:
            chunks.append(current)
            current = para
    if current:
        chunks.append(current)

    # Merge an undersized tail into the previous chunk.
    if len(chunks) >= 2 and len(chunks[-1]) < CHUNK_MIN_TAIL_CHARS:
        tail = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n\n{tail}"
    return chunks
