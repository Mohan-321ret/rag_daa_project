"""
File Utilities
--------------
Helper functions for:
- File validation (extension, size)
- Unique document ID generation
- Text normalisation (unicode, whitespace)
- Safe filename generation
"""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from pathlib import Path

from app.core.config import settings


# ── ID Generation ─────────────────────────────────────────────────────────────

def generate_document_id() -> str:
    """
    Generate a human-readable, unique document ID.
    Format: DOC_<8-char uppercase hex>
    Example: DOC_3F2A1B9C
    """
    short_id = uuid.uuid4().hex[:8].upper()
    return f"{settings.doc_id_prefix}_{short_id}"


# ── Filename helpers ───────────────────────────────────────────────────────────

def get_extension(filename: str) -> str:
    """Return the lowercased file extension including the dot, e.g. '.pdf'."""
    return Path(filename).suffix.lower()


def safe_filename(original: str, doc_id: str) -> str:
    """
    Build a safe internal filename by combining the doc_id and the original
    extension. Strips dangerous characters from the original name.
    Example: DOC_3F2A1B9C_hr_policy.pdf
    """
    stem = re.sub(r"[^\w\-]", "_", Path(original).stem)[:64]
    ext = get_extension(original)
    return f"{doc_id}_{stem}{ext}"


# ── Validation ────────────────────────────────────────────────────────────────

def validate_extension(filename: str) -> None:
    """
    Raise ValueError if the file extension is not in the allowed list.
    Allowed extensions are configured via settings.allowed_ext_list.
    """
    ext = get_extension(filename)
    if ext not in settings.allowed_ext_list:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Allowed types: {', '.join(settings.allowed_ext_list)}"
        )


def validate_file_size(size_bytes: int) -> None:
    """
    Raise ValueError if the file exceeds the configured maximum size.
    """
    if size_bytes == 0:
        raise ValueError("Uploaded file is empty.")
    if size_bytes > settings.max_upload_bytes:
        raise ValueError(
            f"File size {size_bytes / (1024 * 1024):.1f} MB exceeds "
            f"maximum allowed {settings.max_upload_size_mb} MB."
        )


# ── Text Normalisation ────────────────────────────────────────────────────────

def normalize_text(raw: str) -> str:
    """
    Clean and normalise raw extracted text:
    1. NFC unicode normalisation
    2. Replace non-breaking spaces with regular spaces
    3. Collapse multiple blank lines to a maximum of two
    4. Collapse horizontal whitespace (tabs, multiple spaces) to one space
    5. Strip leading/trailing whitespace per line
    6. Strip overall leading/trailing whitespace
    """
    if not raw:
        return ""

    # 1. Unicode NFC normalisation
    text = unicodedata.normalize("NFC", raw)

    # 2. Replace common non-printable / special whitespace variants
    text = text.replace("\u00a0", " ")   # non-breaking space
    text = text.replace("\u200b", "")    # zero-width space
    text = text.replace("\u2019", "'")   # right single quotation mark
    text = text.replace("\u2018", "'")   # left single quotation mark
    text = text.replace("\u201c", '"')   # left double quotation mark
    text = text.replace("\u201d", '"')   # right double quotation mark

    # 3. Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 4. Per-line: collapse tabs and multiple spaces to single space
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]

    # 5. Collapse runs of more than 2 consecutive blank lines
    result_lines: list[str] = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 2:
                result_lines.append("")
        else:
            blank_count = 0
            result_lines.append(line)

    return "\n".join(result_lines).strip()


# ── Word / Char count ─────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    """Return the number of whitespace-separated tokens in *text*."""
    return len(text.split()) if text.strip() else 0


def count_chars(text: str) -> int:
    """Return the total character count of *text*."""
    return len(text)


# ── Temp directory ────────────────────────────────────────────────────────────

def ensure_temp_dir() -> Path:
    """Create the temp upload directory if it doesn't exist and return its Path."""
    tmp = Path(settings.temp_upload_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp
