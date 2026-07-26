"""
Metadata Service
----------------
Extracts document-level metadata by:
1. Reading properties embedded in the document (author, title, etc.)
2. Computing text statistics (word count, character count)
3. Assembling the ExtractedDocumentData DTO

Supported property extraction:
- PDF  : pypdf PdfReader.metadata
- DOCX : python-docx Document.core_properties
- TXT/HTML/PPTX: no embedded properties; defaults are used
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas.document import ExtractedDocumentData
from app.utils.file_utils import count_chars, count_words

logger = logging.getLogger(__name__)


# ── Main entry point ──────────────────────────────────────────────────────────

def build_document_metadata(
    *,
    document_id: str,
    original_filename: str,
    filename: str,
    file_extension: str,
    extracted_text: str,
    ocr_used: bool,
    extraction_duration_s: Optional[float],
    file_path: str | Path,
    department: Optional[str] = None,
    permissions: str = "private",
    language: Optional[str] = None,
) -> ExtractedDocumentData:
    """
    Build a fully populated ExtractedDocumentData DTO.

    1. Determines document_type from the extension.
    2. Attempts to read embedded author/title from the file.
    3. Computes word and character counts.
    4. Returns the assembled DTO.
    """
    document_type = _ext_to_doc_type(file_extension)
    author, title = _extract_native_metadata(Path(file_path), file_extension)

    word_count = count_words(extracted_text)
    char_count = count_chars(extracted_text)

    logger.info(
        "[MetadataService] 📋 Metadata assembled | id=%s type=%s "
        "words=%d chars=%d ocr=%s",
        document_id, document_type, word_count, char_count, ocr_used,
    )

    return ExtractedDocumentData(
        document_id=document_id,
        filename=filename,
        original_filename=original_filename,
        document_type=document_type,
        file_extension=file_extension,
        extracted_text=extracted_text,
        ocr_used=ocr_used,
        author=author,
        title=title,
        department=department,
        permissions=permissions,
        language=language,
        word_count=word_count,
        character_count=char_count,
        extraction_duration_s=extraction_duration_s,
        upload_date=datetime.now(timezone.utc),
    )


# ── Document type mapping ──────────────────────────────────────────────────────

def _ext_to_doc_type(ext: str) -> str:
    """Map a file extension to a human-readable document type label."""
    return {
        ".pdf": "PDF",
        ".docx": "DOCX",
        ".txt": "TXT",
        ".html": "HTML",
        ".pptx": "PPTX",
    }.get(ext.lower(), ext.lstrip(".").upper())


# ── Native metadata extractors ─────────────────────────────────────────────────

def _extract_native_metadata(
    path: Path, ext: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Try to extract author and title from the document's embedded properties.
    Returns (author, title) — either or both may be None.
    """
    try:
        if ext == ".pdf":
            return _pdf_metadata(path)
        elif ext == ".docx":
            return _docx_metadata(path)
    except Exception as exc:
        logger.warning(
            "[MetadataService] Could not read native metadata from %s: %s",
            path.name, exc,
        )
    return None, None


def _pdf_metadata(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Read author and title from PDF metadata using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    author = _clean_meta_str(meta.get("/Author"))
    title = _clean_meta_str(meta.get("/Title"))
    return author, title


def _docx_metadata(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Read core properties from a Word document using python-docx."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    props = doc.core_properties
    author = _clean_meta_str(getattr(props, "author", None))
    title = _clean_meta_str(getattr(props, "title", None))
    return author, title


def _clean_meta_str(value: object) -> Optional[str]:
    """Sanitise a metadata string value – return None for empty/invalid."""
    if not value:
        return None
    s = str(value).strip()
    return s if s else None
