"""
Document Loader Service
-----------------------
Extracts raw text from supported file types:
  - PDF   → PyPDFLoader / pypdf (text-based)
  - DOCX  → python-docx (paragraphs + tables) with docx2txt fallback
  - DOC   → docx2txt / python-docx
  - TXT   → TextLoader (UTF-8 / multi-encoding)
  - HTML  → BSHTMLLoader / BeautifulSoup
  - PPTX  → python-pptx (slides + shapes + text frames)
  - PPT   → python-pptx / UnstructuredPowerPointLoader
  - CSV   → csv module (handles utf-8/latin-1)
  - XLSX  → openpyxl / pandas
  - XLS   → openpyxl / pandas

Returns raw (un-normalised) text; normalisation is done in file_utils.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Tuple

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
        elif ext in (".docx", ".doc"):
            raw_text = _load_docx(path)
        elif ext in (".txt", ".md"):
            raw_text = _load_txt(path)
        elif ext in (".html", ".htm"):
            raw_text = _load_html(path)
        elif ext in (".pptx", ".ppt"):
            raw_text = _load_pptx(path)
        elif ext == ".csv":
            raw_text = _load_csv(path)
        elif ext in (".xlsx", ".xls"):
            raw_text = _load_excel(path)
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
    """Attempt text extraction with LangChain's PyPDFLoader or pypdf."""
    try:
        from langchain_community.document_loaders import PyPDFLoader
        loader = PyPDFLoader(str(path))
        pages = loader.load()
        text = "\n".join(p.page_content for p in pages if p.page_content)
        if text.strip():
            return text
    except Exception as exc:
        err_lower = str(exc).lower()
        if "encrypt" in err_lower or "password" in err_lower:
            raise RuntimeError("The PDF is password-protected and cannot be processed.") from exc

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        return text
    except Exception as exc2:
        raise RuntimeError(f"PDF loading failed: {exc2}") from exc2


# ── DOCX / DOC ─────────────────────────────────────────────────────────────────

def _load_docx(path: Path) -> str:
    """Extract text from Word documents (.docx, .doc) using python-docx or docx2txt."""
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(str(path))
        full_text = []
        for p in doc.paragraphs:
            if p.text.strip():
                full_text.append(p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                row_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_text:
                    full_text.append(" | ".join(row_text))
        if full_text:
            return "\n".join(full_text)
    except Exception as exc:
        logger.warning("[DocumentLoader] python-docx failed for %s, trying docx2txt: %s", path.name, exc)

    try:
        import docx2txt
        text = docx2txt.process(str(path))
        if text and text.strip():
            return text.strip()
    except Exception as exc2:
        logger.warning("[DocumentLoader] docx2txt failed for %s: %s", path.name, exc2)

    try:
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(str(path))
        docs = loader.load()
        return "\n".join(d.page_content for d in docs if d.page_content)
    except Exception as exc3:
        raise RuntimeError(f"DOCX loading failed for '{path.name}': {exc3}") from exc3


# ── TXT / MD ───────────────────────────────────────────────────────────────────

def _load_txt(path: Path) -> str:
    """Load plain text / markdown with encoding fallbacks."""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


# ── HTML ───────────────────────────────────────────────────────────────────────

def _load_html(path: Path) -> str:
    """Extract visible text from HTML files."""
    try:
        from langchain_community.document_loaders import BSHTMLLoader
        loader = BSHTMLLoader(str(path), open_encoding="utf-8")
        docs = loader.load()
        return "\n".join(d.page_content for d in docs if d.page_content)
    except Exception:
        from bs4 import BeautifulSoup
        html_content = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator="\n", strip=True)


# ── PPTX / PPT ─────────────────────────────────────────────────────────────────

def _load_pptx(path: Path) -> str:
    """Extract text from PowerPoint slides (.pptx, .ppt)."""
    try:
        from pptx import Presentation
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

        if slide_texts:
            return "\n\n".join(slide_texts)
    except Exception as exc:
        logger.warning("[DocumentLoader] python-pptx failed for %s: %s", path.name, exc)

    try:
        from langchain_community.document_loaders import UnstructuredPowerPointLoader
        loader = UnstructuredPowerPointLoader(str(path))
        docs = loader.load()
        return "\n".join(d.page_content for d in docs if d.page_content)
    except Exception as exc2:
        raise RuntimeError(f"PowerPoint loading failed for '{path.name}': {exc2}") from exc2


# ── CSV ────────────────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> str:
    """Extract text from CSV files."""
    import csv
    lines = []
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            with open(path, mode="r", encoding=enc, errors="replace") as f:
                reader = csv.reader(f)
                for row in reader:
                    row_str = " | ".join(cell.strip() for cell in row if cell.strip())
                    if row_str:
                        lines.append(row_str)
            if lines:
                return "\n".join(lines)
        except Exception:
            continue
    raise RuntimeError(f"Failed to parse CSV file '{path.name}'.")


# ── Excel (.xlsx / .xls) ───────────────────────────────────────────────────────

def _load_excel(path: Path) -> str:
    """Extract text from Excel sheets (.xlsx, .xls) using openpyxl or pandas."""
    sheet_texts = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows_text = []
            for row in sheet.iter_rows(values_only=True):
                cell_vals = [str(val).strip() for val in row if val is not None and str(val).strip() != ""]
                if cell_vals:
                    rows_text.append(" | ".join(cell_vals))
            if rows_text:
                sheet_texts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows_text))
        if sheet_texts:
            return "\n\n".join(sheet_texts)
    except Exception as exc:
        logger.warning("[DocumentLoader] openpyxl failed for %s, trying pandas: %s", path.name, exc)

    try:
        import pandas as pd
        excel_file = pd.ExcelFile(str(path))
        for sheet_name in excel_file.sheet_names:
            df = excel_file.parse(sheet_name)
            csv_text = df.to_csv(index=False, sep=" | ")
            if csv_text.strip():
                sheet_texts.append(f"[Sheet: {sheet_name}]\n" + csv_text.strip())
        if sheet_texts:
            return "\n\n".join(sheet_texts)
    except Exception as exc2:
        raise RuntimeError(f"Excel loading failed for '{path.name}': {exc2}") from exc2

    raise RuntimeError(f"Excel file '{path.name}' contained no readable text.")
