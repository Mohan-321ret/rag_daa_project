"""
Documents API Router – Module 1: Enterprise Knowledge Ingestion
---------------------------------------------------------------
Endpoint: POST /api/v1/documents/upload

Full pipeline per upload:
  1. Validate file (extension, size, not empty)
  2. Save temporarily to disk
  3. Load text via LangChain loader (document_loader)
  4. If PDF and no text → OCR fallback (ocr_service)
  5. Normalise extracted text (file_utils)
  6. Extract/build metadata (metadata_service)
  7. Persist to PostgreSQL (storage_service)
  8. Delete temporary file (cleanup_service)   ← always runs
  9. Return response
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.schemas.document import DocumentUploadResponse
from app.services.cleanup_service import CleanupService
from app.services.document_loader import load_document
from app.services.metadata_service import build_document_metadata
from app.services.ocr_service import run_ocr_on_pdf
from app.services.storage_service import StorageService
from app.utils.file_utils import (
    ensure_temp_dir,
    generate_document_id,
    get_extension,
    normalize_text,
    safe_filename,
    validate_extension,
    validate_file_size,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Ingestion"])


# ── POST /documents/upload ────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a document",
    description=(
        "Accepts a document file (PDF, DOCX, TXT, HTML, PPTX), "
        "extracts text, stores metadata in PostgreSQL, and deletes the "
        "temporary file. The original file is NEVER persisted."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="Document to ingest"),
    department: str | None = Form(
        default=None, description="Department label (optional)"
    ),
    permissions: str = Form(
        default="private", description="Access level: private | internal | public"
    ),
    language: str | None = Form(
        default=None, description="Document language hint (optional)"
    ),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Full ingestion pipeline endpoint.

    - Validates file type and size.
    - Extracts text (with OCR fallback for image PDFs).
    - Saves metadata to PostgreSQL.
    - Deletes the temporary file.
    """

    # ── 1. Basic validation ───────────────────────────────────────────────────
    logger.info(
        "[Upload] 📥 Upload received | filename=%s content_type=%s",
        file.filename, file.content_type,
    )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )

    original_filename = file.filename
    ext = get_extension(original_filename)

    # Extension check
    try:
        validate_extension(original_filename)
    except ValueError as exc:
        logger.warning("[Upload] ❌ Rejected unsupported type: %s", original_filename)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )

    # Read the full file into memory to check size
    file_bytes = await file.read()
    try:
        validate_file_size(len(file_bytes))
    except ValueError as exc:
        logger.warning(
            "[Upload] ❌ Rejected oversized/empty file: %s (%d bytes)",
            original_filename, len(file_bytes),
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    # ── 2. Generate ID and save temporarily ───────────────────────────────────
    document_id = generate_document_id()
    safe_name = safe_filename(original_filename, document_id)
    tmp_dir = ensure_temp_dir()
    tmp_path = tmp_dir / safe_name

    try:
        tmp_path.write_bytes(file_bytes)
        logger.info(
            "[Upload] 💾 Temp file saved: %s (%d bytes)", safe_name, len(file_bytes)
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not write temporary file: {exc}",
        )

    # ── 3-4. Text extraction (loader + OCR fallback) ───────────────────────────
    ocr_used = False
    extraction_duration_s: float | None = None

    try:
        raw_text, extraction_duration_s = load_document(tmp_path)
        logger.info("[Upload] 📄 Document loaded | chars=%d", len(raw_text))

        # OCR fallback: if PDF returned no text, invoke Tesseract
        if ext == ".pdf" and not raw_text.strip():
            logger.info(
                "[Upload] ℹ️  PDF has no extractable text – invoking OCR for %s",
                safe_name,
            )
            raw_text, extraction_duration_s = run_ocr_on_pdf(tmp_path)
            ocr_used = True
            logger.info(
                "[Upload] ✅ OCR completed | chars=%d", len(raw_text)
            )

        # Final check – if still empty after OCR
        if not raw_text.strip():
            raise RuntimeError(
                "Text extraction produced no content. "
                "The file may be corrupt or contain only unsupported content."
            )

    except RuntimeError as exc:
        # Best-effort cleanup before raising
        CleanupService.safe_delete(tmp_path)
        logger.error("[Upload] ❌ Extraction failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        CleanupService.safe_delete(tmp_path)
        logger.error("[Upload] ❌ Unexpected extraction error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during text extraction: {exc}",
        )

    # ── 5. Normalise text ─────────────────────────────────────────────────────
    clean_text = normalize_text(raw_text)
    logger.info("[Upload] 🧹 Text normalised | chars=%d", len(clean_text))

    # ── 6. Build metadata ─────────────────────────────────────────────────────
    doc_data = build_document_metadata(
        document_id=document_id,
        original_filename=original_filename,
        filename=safe_name,
        file_extension=ext,
        extracted_text=clean_text,
        ocr_used=ocr_used,
        extraction_duration_s=extraction_duration_s,
        file_path=tmp_path,
        department=department,
        permissions=permissions,
        language=language,
    )
    logger.info(
        "[Upload] 📋 Metadata built | words=%d chars=%d",
        doc_data.word_count, doc_data.character_count,
    )

    # ── 7. Persist to PostgreSQL ───────────────────────────────────────────────
    storage = StorageService(db)
    try:
        saved_doc = storage.save_document(doc_data)
        logger.info(
            "[Upload] ✅ Stored in PostgreSQL | id=%s", saved_doc.document_id
        )
    except RuntimeError as exc:
        CleanupService.safe_delete(tmp_path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    # ── 8. Delete temp file (MANDATORY – always runs) ─────────────────────────
    CleanupService.delete_temp_file(tmp_path)
    logger.info("[Upload] 🗑️  Temporary file deleted: %s", safe_name)

    # ── 9. Return response ────────────────────────────────────────────────────
    logger.info(
        "[Upload] 🎉 Ingestion complete | id=%s status=indexed",
        saved_doc.document_id,
    )
    return DocumentUploadResponse(
        success=True,
        document_id=saved_doc.document_id,
        filename=saved_doc.filename,
        original_filename=saved_doc.original_filename,
        document_type=saved_doc.document_type,
        ocr_used=saved_doc.ocr_used,
        word_count=saved_doc.word_count,
        character_count=saved_doc.character_count,
        extraction_duration_s=saved_doc.extraction_duration_s,
        processing_status=saved_doc.processing_status,
        upload_date=saved_doc.upload_date,
    )


# ── GET /documents/{document_id} ──────────────────────────────────────────────

@router.get(
    "/{document_id}",
    summary="Retrieve document metadata",
    tags=["Document Ingestion"],
)
def get_document(document_id: str, db: Session = Depends(get_db)):
    """Return the metadata and extracted text for a specific document."""
    storage = StorageService(db)
    doc = storage.get_by_document_id(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    return {
        "document_id": doc.document_id,
        "filename": doc.original_filename,
        "document_type": doc.document_type,
        "author": doc.author,
        "title": doc.title,
        "department": doc.department,
        "permissions": doc.permissions,
        "language": doc.language,
        "upload_date": doc.upload_date,
        "ocr_used": doc.ocr_used,
        "word_count": doc.word_count,
        "character_count": doc.character_count,
        "extraction_duration_s": doc.extraction_duration_s,
        "processing_status": doc.processing_status,
        "extracted_text_preview": (
            doc.extracted_text[:500] + "…"
            if doc.extracted_text and len(doc.extracted_text) > 500
            else doc.extracted_text
        ),
    }


# ── GET /documents ────────────────────────────────────────────────────────────

@router.get(
    "/",
    summary="List all documents",
    tags=["Document Ingestion"],
)
def list_documents(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Return a paginated list of all ingested document records."""
    storage = StorageService(db)
    docs = storage.list_documents(skip=skip, limit=limit)
    return {
        "total": len(docs),
        "skip": skip,
        "limit": limit,
        "documents": [
            {
                "document_id": d.document_id,
                "original_filename": d.original_filename,
                "document_type": d.document_type,
                "word_count": d.word_count,
                "processing_status": d.processing_status,
                "upload_date": d.upload_date,
                "ocr_used": d.ocr_used,
            }
            for d in docs
        ],
    }
