"""
Documents API Router – Module 1 + Module 2 (Phase 3)
-----------------------------------------------------
Endpoint: POST /api/v1/documents/upload

Admin Panel: Data Injection Management — upload is a genuine async job, not
a synchronous call that happens to take a while. The endpoint below only
does cheap, fast-failing work (validation + temp save + IngestionJob row)
before returning 202; everything from text extraction onward runs in
_run_ingestion_job(), a FastAPI BackgroundTask with its OWN DB session (see
that function's docstring for why). Per-stage progress is persisted for
real via app/services/ingestion_job_service.StageReporter — the frontend
polls GET /ingestion-jobs/{job_id} rather than assuming success the moment
this POST returns. See app/models/ingestion_job.py for the full pipeline:

  Upload → Document Loader → OCR (if required) → Text Cleaning →
  Noise Removal → Language Detection → Chunking → Embedding →
  Vector Index → PostgreSQL Metadata → Neo4j
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import SessionLocal, get_db
from app.models.document import Document
from app.models.domain import Domain
from app.models.user import User
from app.schemas.ingestion_job import UploadAcceptedResponse
from app.services import ingestion_job_service
from app.services.ingestion_job_service import StageReporter
from app.services.auth_service import current_role, require_permission
from app.services.cleanup_service import CleanupService
from app.services.document_access_service import (
    assert_can_upload_to_domain,
    assert_document_visible,
    grant_restricted_access,
    scope_document_list,
    validate_visibility_domain,
)
from app.services.document_loader import load_document
from app.services.metadata_service import build_document_metadata
from app.services.ocr_service import run_ocr_on_pdf
from app.services.storage_service import StorageService
from app.services.evolution_service import process_document
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


# ── Background task: runs the actual pipeline after 202 is returned ──────────

def _run_ingestion_job(
    job_id: str,
    document_id: str,
    tmp_path: Path,
    safe_name: str,
    original_filename: str,
    ext: str,
    department: Optional[str],
    domain_id: Optional[str],
    visibility: str,
    permissions: str,
    restricted_user_ids: Optional[str],
    language: Optional[str],
    user_id: str,
) -> None:
    """
    Runs in a worker thread (Starlette executes sync BackgroundTasks via
    run_in_threadpool) — MUST open its own SQLAlchemy session. The request's
    session that created the IngestionJob row is closed the instant the
    request returns, well before this function actually executes.
    """
    db = SessionLocal()
    reporter = StageReporter(db, job_id)
    try:
        reporter("upload", "running")
        reporter("upload", "completed")

        reporter("document_loader", "running")
        try:
            raw_text, extraction_duration_s = load_document(tmp_path)
        except Exception as exc:
            reporter("document_loader", "failed", str(exc))
            raise
        reporter("document_loader", "completed")

        ocr_used = False
        if ext == ".pdf" and not raw_text.strip():
            reporter("ocr", "running")
            try:
                raw_text, extraction_duration_s = run_ocr_on_pdf(tmp_path)
                ocr_used = True
            except Exception as exc:
                reporter("ocr", "failed", str(exc))
                raise
            reporter("ocr", "completed")
        else:
            reporter("ocr", "skipped")

        if not raw_text.strip():
            raise RuntimeError(
                "Text extraction produced no content. "
                "The file may be corrupt or contain only unsupported content."
            )

        cleaned_extracted_text = normalize_text(raw_text)

        doc_data = build_document_metadata(
            document_id=document_id,
            original_filename=original_filename,
            filename=safe_name,
            file_extension=ext,
            extracted_text=cleaned_extracted_text,
            ocr_used=ocr_used,
            extraction_duration_s=extraction_duration_s,
            file_path=tmp_path,
            department=department,
            permissions=permissions,
            language=language,
            domain_id=domain_id,
            visibility=visibility,
            owner_id=user_id,
            uploaded_by_id=user_id,
        )

        # process_document() catches its own pipeline exceptions internally
        # (marks the Document row 'failed' and returns rather than raising)
        # so success is NOT "no exception" — it's saved_doc.processing_status.
        # The StageReporter passed as on_stage already recorded the precise
        # failing stage/error before that swallow happens; this is a
        # catch-all in case a failure occurs outside any tracked stage span
        # (e.g. diff/drift/conflict detection in the new-version path).
        summary = process_document(
            db, doc_data, language_hint=language, source="upload", on_stage=reporter,
        )
        saved_doc = summary["document"]
        action = summary["action"]

        if saved_doc.processing_status == "failed":
            ingestion_job_service.mark_failed(
                db, job_id, summary.get("error") or "Processing failed."
            )
            return

        if visibility == "restricted" and restricted_user_ids and action != "unchanged":
            user_ids = [u.strip() for u in restricted_user_ids.split(",") if u.strip()]
            grant_restricted_access(
                db, saved_doc.document_id, user_ids=user_ids, granted_by=uuid.UUID(user_id)
            )
            db.commit()

        ingestion_job_service.mark_completed(db, job_id, saved_doc.document_id, action=action)
        logger.info(
            "[IngestionJob] 🎉 %s complete | document=%s action=%s",
            job_id, saved_doc.document_id, action,
        )

    except Exception as exc:
        logger.error("[IngestionJob] ❌ %s failed: %s", job_id, exc)
        ingestion_job_service.mark_failed(db, job_id, str(exc))
    finally:
        CleanupService.delete_temp_file(tmp_path)
        logger.info("[IngestionJob] 🗑️  Temporary file deleted: %s", safe_name)
        db.close()


# ── POST /documents/upload ────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for ingestion (async)",
    description=(
        "Accepts a document file (PDF, DOCX, TXT, HTML, PPTX), validates it, "
        "and queues a background ingestion job. The original file is NEVER "
        "persisted. Returns a job_id immediately — poll "
        "GET /ingestion-jobs/{job_id} for real per-stage progress and the "
        "final document_id. This response is a receipt, not a confirmation "
        "of success."
    ),
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Document to ingest"),
    department: str | None = Form(
        default=None, description="Department label (optional, free text)"
    ),
    domain_id: str | None = Form(
        default=None, description="Domain UUID — required unless visibility='global'"
    ),
    visibility: str = Form(
        default="domain", description="Access scope: global | domain | restricted"
    ),
    permissions: str = Form(
        default="private", description="Legacy free-text label: private | internal | public"
    ),
    restricted_user_ids: str | None = Form(
        default=None, description="Comma-separated user UUIDs granted access (visibility='restricted' only)"
    ),
    language: str | None = Form(
        default=None, description="Document language hint (optional)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    caller_role: Role = Depends(current_role),
) -> UploadAcceptedResponse:
    """
    Validates the upload, saves it to a temp path, creates a queued
    IngestionJob, and schedules the real pipeline as a background task.
    """

    # ── 1. Basic validation ───────────────────────────────────────────────────
    logger.info(
        "[Upload] 📥 Upload received | filename=%s content_type=%s",
        file.filename, file.content_type,
    )

    # ── Domain Assignment + Permission Assignment (pipeline steps, ahead of
    # any text extraction so bad input fails fast/cheaply) ─────────────────────
    visibility = visibility.strip().lower()
    validate_visibility_domain(visibility, domain_id)
    if domain_id and db.query(Domain.id).filter(Domain.id == domain_id).first() is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown domain id: {domain_id}")
    assert_can_upload_to_domain(db, current_user, caller_role, domain_id)

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

    # ── 3. Create the queued IngestionJob + schedule the background task ─────
    # Everything from here on (extraction, OCR, cleaning, chunking, embedding,
    # indexing) happens OFF the request thread — see _run_ingestion_job()'s
    # docstring above for why it needs its own DB session.
    job = ingestion_job_service.create_job(
        db, original_filename=original_filename, created_by_user_id=current_user.id,
    )
    background_tasks.add_task(
        _run_ingestion_job,
        job_id=job.job_id,
        document_id=document_id,
        tmp_path=tmp_path,
        safe_name=safe_name,
        original_filename=original_filename,
        ext=ext,
        department=department,
        domain_id=domain_id,
        visibility=visibility,
        permissions=permissions,
        restricted_user_ids=restricted_user_ids,
        language=language,
        user_id=str(current_user.id),
    )
    logger.info(
        "[Upload] 🚀 Job %s queued for '%s' | document_id=%s",
        job.job_id, original_filename, document_id,
    )

    return UploadAcceptedResponse(
        job_id=job.job_id,
        status=job.status,
        original_filename=original_filename,
    )


# ── GET /documents/{document_id} ──────────────────────────────────────────────

@router.get(
    "/{document_id}",
    summary="Retrieve document metadata",
    tags=["Document Ingestion"],
)
def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
):
    """Return the metadata and extracted text for a specific document."""
    storage = StorageService(db)
    doc = storage.get_by_document_id(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    assert_document_visible(db, current_user, caller_role, doc)
    return {
        "document_id": doc.document_id,
        "filename": doc.original_filename,
        "document_type": doc.document_type,
        "author": doc.author,
        "title": doc.title,
        "department": doc.department,
        "domain_id": str(doc.domain_id) if doc.domain_id else None,
        "visibility": doc.visibility,
        "permissions": doc.permissions,
        "owner_id": str(doc.owner_id) if doc.owner_id else None,
        "uploaded_by_id": str(doc.uploaded_by_id) if doc.uploaded_by_id else None,
        "language": doc.language,
        "upload_date": doc.upload_date,
        "ocr_used": doc.ocr_used,
        "word_count": doc.word_count,
        "character_count": doc.character_count,
        "extraction_duration_s": doc.extraction_duration_s,
        "processing_status": doc.processing_status,
        "version": doc.version,
        "is_latest": doc.is_latest,
        "previous_version_id": doc.previous_version_id,
        "content_hash": doc.content_hash,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
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
    domain_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
):
    """
    Return a paginated list of ingested document records, scoped to what
    *current_user* is allowed to see (see document_access_service.scope_document_list —
    global documents to everyone, domain documents to same-domain members,
    restricted documents to explicit grantees; domain-unrestricted roles see all).
    """
    query = scope_document_list(db.query(Document), db, current_user, caller_role)
    if domain_id:
        query = query.filter(Document.domain_id == domain_id)

    total = query.count()
    docs = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
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
                "department": d.department,
                "domain_id": str(d.domain_id) if d.domain_id else None,
                "visibility": d.visibility,
                "language": d.language,
                "version": d.version,
            }
            for d in docs
        ],
    }
