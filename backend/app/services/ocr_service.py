"""
OCR Service
-----------
Invoked when a PDF yields no extractable text (i.e., it is a scanned document).

Workflow:
  PDF → convert pages to PIL images (pdf2image) → Tesseract OCR each page
       → combine all page texts → return full text string

Requirements:
  - Tesseract must be installed on the host OS.
    Windows: https://github.com/UB-Mannheim/tesseract/wiki
    Linux:   apt-get install -y tesseract-ocr
  - pdf2image requires poppler:
    Windows: https://github.com/oschwartz10612/poppler-windows
    Linux:   apt-get install -y poppler-utils
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def run_ocr_on_pdf(file_path: str | Path) -> Tuple[str, float]:
    """
    Convert each PDF page to an image and run Tesseract OCR on it.

    Args:
        file_path: Path to the (temporary) PDF file.

    Returns:
        Tuple of (extracted_text, duration_seconds).

    Raises:
        RuntimeError: If OCR completely fails or produces no output.
    """
    import pytesseract
    from pdf2image import convert_from_path

    path = Path(file_path)
    logger.info("[OCRService] 🔍 Starting OCR on: %s", path.name)
    start = time.perf_counter()

    try:
        # ── Step 1: Convert PDF pages to PIL images ───────────────────────────
        logger.info("[OCRService] Converting PDF pages to images …")
        images = convert_from_path(
            str(path),
            dpi=300,           # High resolution for better OCR accuracy
            fmt="png",
            thread_count=4,
        )
        logger.info("[OCRService] Converted %d page(s) to images.", len(images))

        if not images:
            raise RuntimeError("pdf2image returned no pages. PDF may be corrupt.")

        # ── Step 2: OCR each page ─────────────────────────────────────────────
        page_texts: list[str] = []
        for page_num, image in enumerate(images, start=1):
            logger.debug("[OCRService] OCR-ing page %d …", page_num)
            page_text: str = pytesseract.image_to_string(
                image,
                lang="eng",            # default language; can be configured
                config="--psm 3",      # automatic page segmentation
            )
            if page_text.strip():
                page_texts.append(page_text)

        # ── Step 3: Combine all pages ─────────────────────────────────────────
        full_text = "\n\n".join(page_texts)
        duration = round(time.perf_counter() - start, 4)

        if not full_text.strip():
            raise RuntimeError(
                "OCR completed but extracted no text. "
                "The PDF may contain images without readable text."
            )

        logger.info(
            "[OCRService] ✅ OCR complete: %d pages, %d chars, %.3fs",
            len(images), len(full_text), duration,
        )
        return full_text, duration

    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("[OCRService] ❌ OCR failed: %s", exc)
        raise RuntimeError(f"OCR processing failed: {exc}") from exc


def is_ocr_available() -> bool:
    """
    Check whether Tesseract is installed and reachable.
    Used in the health check endpoint.
    """
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
