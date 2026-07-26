"""
Document Loader Service
-----------------------
Uses LangChain Document Loaders to extract text from supported file types:
  - PDF  → PyPDFLoader (text-based)
  - DOCX → Docx2txtLoader
  - TXT  → TextLoader
  - HTML → BSHTMLLoader
  - PPTX → UnstructuredPowerPointLoader (falls back to python-pptx)

Returns raw (un-normalised) text; normalisation is done in file_utils.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Tuple

from app.utils.file_utils import normalize_text

logger = logging.getLogger(__name__)


# ── Loader dispatch ───────────────────────────────────────────────────────────

def load_document(file_path: str | Path) -> Tuple[str, float]:
    """
    Load a document and return (raw_text, duration_seconds).

    Raises:
        ValueError – unsupported extension
        RuntimeError – loader failure / empty content
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    logger.info("[DocumentLoader] Loading document: %s (type=%s)", path.name, ext)
    start = time.perf_counter()

    try:
        if ext == ".pdf":
            raw_text = _load_pdf(path)
        elif ext == ".docx":
            raw_text = _load_docx(path)
        elif ext == ".txt":
            raw_text = _load_txt(path)
        elif ext == ".html":
            raw_text = _load_html(path)
        elif ext == ".pptx":
            raw_text = _load_pptx(path)
        else:
            raise ValueError(f"Unsupported file extension: '{ext}'")

        duration = round(time.perf_counter() - start, 4)
        logger.info(
            "[DocumentLoader] ✅ Loaded %s in %.3fs, raw chars=%d",
            path.name, duration, len(raw_text),
        )
        return raw_text, duration

    except ValueError:
        raise
    except Exception as exc:
        logger.error(
            "[DocumentLoader] ❌ Failed to load %s: %s", path.name, exc
        )
        raise RuntimeError(
            f"Failed to load document '{path.name}': {exc}"
        ) from exc


# ── PDF ────────────────────────────────────────────────────────────────────────

def _load_pdf(path: Path) -> str:
    """
    Attempt text extraction with LangChain's PyPDFLoader.
    If the result is empty (scanned/image PDF), return empty string
    so the caller can invoke OCR as a fallback.
    """
    try:
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(str(path))
        pages = loader.load()
        text = "\n".join(p.page_content for p in pages if p.page_content)
        return text
    except Exception as exc:
        # Distinguish password-protected PDFs
        err_lower = str(exc).lower()
        if "encrypt" in err_lower or "password" in err_lower:
            raise RuntimeError(
                "The PDF is password-protected and cannot be processed."
            ) from exc
        raise RuntimeError(f"PDF loading failed: {exc}") from exc


# ── DOCX ───────────────────────────────────────────────────────────────────────

def _load_docx(path: Path) -> str:
    """Extract text from a Word document using LangChain's Docx2txtLoader."""
    from langchain_community.document_loaders import Docx2txtLoader
    loader = Docx2txtLoader(str(path))
    docs = loader.load()
    return "\n".join(d.page_content for d in docs if d.page_content)


# ── TXT ────────────────────────────────────────────────────────────────────────

def _load_txt(path: Path) -> str:
    """Load a plain-text file using LangChain's TextLoader (UTF-8)."""
    from langchain_community.document_loaders import TextLoader
    loader = TextLoader(str(path), encoding="utf-8")
    docs = loader.load()
    return "\n".join(d.page_content for d in docs if d.page_content)


# ── HTML ───────────────────────────────────────────────────────────────────────

def _load_html(path: Path) -> str:
    """Extract visible text from HTML using LangChain's BSHTMLLoader."""
    from langchain_community.document_loaders import BSHTMLLoader
    loader = BSHTMLLoader(str(path), open_encoding="utf-8")
    docs = loader.load()
    return "\n".join(d.page_content for d in docs if d.page_content)


# ── PPTX ───────────────────────────────────────────────────────────────────────

def _load_pptx(path: Path) -> str:
    """
    Extract text from PowerPoint slides using python-pptx.
    Iterates all shapes across all slides and collects text frames.
    """
    from pptx import Presentation  # python-pptx

    prs = Presentation(str(path))
    slide_texts: list[str] = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        shapes_text: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = " ".join(run.text for run in para.runs if run.text)
                    if line.strip():
                        shapes_text.append(line)
        if shapes_text:
            slide_texts.append(f"[Slide {slide_num}]\n" + "\n".join(shapes_text))

    return "\n\n".join(slide_texts)
