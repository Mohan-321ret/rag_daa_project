"""
Ticket Attachment Ingestion Service — Phase 2.7
-----------------------------------------------
Handles uploading and processing knowledge base documents associated with support tickets.
Reuses the core document processing pipeline (load_document -> text_cleaner -> chunking_service -> embedding_service -> FAISS vector_store -> postgres_metadata).
Tracks processing status (PENDING, PROCESSING, COMPLETED, FAILED).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.db.database import SessionLocal
from app.models.document import Document
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment, TicketAttachmentStatus, new_attachment_id
from app.models.user import User
from app.services import ingestion_job_service
from app.services.ticket_service import can_user_access_ticket
from app.services.cleanup_service import CleanupService
from app.services.document_loader import load_document
from app.services.evolution_service import process_document
from app.services.ingestion_job_service import StageReporter
from app.services.metadata_service import build_document_metadata
from app.services.ocr_service import run_ocr_on_pdf
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


def _run_ticket_attachment_ingestion_job(
    job_id: str,
    attachment_db_id: uuid.UUID,
    document_id: str,
    tmp_path: Path,
    safe_name: str,
    original_filename: str,
    ext: str,
    user_id: str,
) -> None:
    """
    Background worker function that executes document ingestion for a ticket attachment.
    MUST open its own SQLAlchemy DB session.
    """
    db = SessionLocal()
    reporter = StageReporter(db, job_id)
    try:
        attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_db_id).first()
        if not attachment:
            logger.error("[TicketKB] Attachment %s not found in DB", attachment_db_id)
            return

        ticket = db.query(Ticket).filter(Ticket.ticket_id == attachment.ticket_id).first()
        if not ticket:
            logger.error("[TicketKB] Ticket %s not found for attachment %s", attachment.ticket_id, attachment_db_id)
            attachment.status = TicketAttachmentStatus.FAILED.value
            attachment.error_message = f"Ticket '{attachment.ticket_id}' no longer exists."
            db.commit()
            ingestion_job_service.mark_failed(db, job_id, attachment.error_message)
            return

        attachment.status = TicketAttachmentStatus.PROCESSING.value
        db.commit()

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

        cleaned_text = normalize_text(raw_text)

        domain_id_str = str(ticket.routed_domain_id) if ticket.routed_domain_id else None

        doc_data = build_document_metadata(
            document_id=document_id,
            original_filename=original_filename,
            filename=safe_name,
            file_extension=ext,
            extracted_text=cleaned_text,
            ocr_used=ocr_used,
            extraction_duration_s=extraction_duration_s,
            file_path=tmp_path,
            department=ticket.domain,
            permissions="private",
            domain_id=domain_id_str,
            visibility="domain",
            owner_id=user_id,
            uploaded_by_id=user_id,
        )

        summary = process_document(
            db, doc_data, language_hint=None, source="ticket_resolution", on_stage=reporter
        )
        saved_doc: Document = summary["document"]
        action = summary["action"]

        if saved_doc.processing_status == "failed":
            error_msg = summary.get("error") or "Processing failed."
            attachment.status = TicketAttachmentStatus.FAILED.value
            attachment.error_message = error_msg
            db.commit()
            ingestion_job_service.mark_failed(db, job_id, error_msg)
            return

        # Success: Associate document with ticket
        attachment.status = TicketAttachmentStatus.COMPLETED.value
        attachment.document_id = saved_doc.document_id
        attachment.error_message = None

        if saved_doc not in ticket.documents:
            ticket.documents.append(saved_doc)

        # Append to ticket.supporting_document_ids if present
        current_docs = []
        if ticket.supporting_document_ids:
            current_docs = [d.strip() for d in ticket.supporting_document_ids.split(",") if d.strip()]
        if saved_doc.document_id not in current_docs:
            current_docs.append(saved_doc.document_id)
            ticket.supporting_document_ids = ",".join(current_docs)

        db.commit()

        ingestion_job_service.mark_completed(db, job_id, saved_doc.document_id, action=action)
        logger.info(
            "[TicketKB] 🎉 Attachment %s ingestion complete | doc=%s ticket=%s",
            attachment.attachment_id, saved_doc.document_id, ticket.ticket_id,
        )

    except Exception as exc:
        logger.error("[TicketKB] ❌ Attachment ingestion failed: %s", exc)
        try:
            attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_db_id).first()
            if attachment:
                attachment.status = TicketAttachmentStatus.FAILED.value
                attachment.error_message = str(exc)
                db.commit()
        except Exception:
            pass
        ingestion_job_service.mark_failed(db, job_id, str(exc))
    finally:
        CleanupService.delete_temp_file(tmp_path)
        db.close()


def upload_ticket_attachment(
    db: Session,
    ticket_id: str,
    file_bytes: bytes,
    original_filename: str,
    current_user: User,
    caller_role: Role,
    background_tasks: Optional[BackgroundTasks] = None,
    sync_processing: bool = False,
) -> TicketAttachment:
    """
    Validates upload, saves temporary file, creates TicketAttachment & IngestionJob rows,
    and runs document ingestion (async background task or sync).
    """
    # ── 1. Retrieve ticket & authorize user ───────────────────────────────────
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )

    # Permission check: User must be able to view/edit the ticket
    if not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User is not authorized to upload knowledge-base files for ticket '{ticket_id}'.",
        )

    # ── 2. Validate file ──────────────────────────────────────────────────────
    if not original_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )

    try:
        validate_extension(original_filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )

    try:
        validate_file_size(len(file_bytes))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    # ── 3. Save temporary file ────────────────────────────────────────────────
    document_id = generate_document_id()
    safe_name = safe_filename(original_filename, document_id)
    ext = get_extension(original_filename)
    tmp_dir = ensure_temp_dir()
    tmp_path = tmp_dir / safe_name

    try:
        tmp_path.write_bytes(file_bytes)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not write temporary file: {exc}",
        )

    # ── 4. Create TicketAttachment & IngestionJob rows ───────────────────────
    attachment = TicketAttachment(
        attachment_id=new_attachment_id(),
        ticket_id=ticket.ticket_id,
        original_filename=original_filename,
        file_type=ext.lstrip(".").upper(),
        file_size=len(file_bytes),
        status=TicketAttachmentStatus.PENDING.value,
        uploaded_by_id=current_user.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    job = ingestion_job_service.create_job(
        db, original_filename=original_filename, created_by_user_id=current_user.id
    )
    attachment.job_id = job.job_id
    db.commit()
    db.refresh(attachment)

    # ── 5. Schedule or run ingestion pipeline ────────────────────────────────
    if sync_processing:
        _run_ticket_attachment_ingestion_job(
            job_id=job.job_id,
            attachment_db_id=attachment.id,
            document_id=document_id,
            tmp_path=tmp_path,
            safe_name=safe_name,
            original_filename=original_filename,
            ext=ext,
            user_id=str(current_user.id),
        )
        db.refresh(attachment)
    elif background_tasks is not None:
        background_tasks.add_task(
            _run_ticket_attachment_ingestion_job,
            job_id=job.job_id,
            attachment_db_id=attachment.id,
            document_id=document_id,
            tmp_path=tmp_path,
            safe_name=safe_name,
            original_filename=original_filename,
            ext=ext,
            user_id=str(current_user.id),
        )
    else:
        # Fallback to sync processing if no background_tasks queue passed
        _run_ticket_attachment_ingestion_job(
            job_id=job.job_id,
            attachment_db_id=attachment.id,
            document_id=document_id,
            tmp_path=tmp_path,
            safe_name=safe_name,
            original_filename=original_filename,
            ext=ext,
            user_id=str(current_user.id),
        )
        db.refresh(attachment)

    return attachment


def list_ticket_attachments(
    db: Session, ticket_id: str, current_user: User, caller_role: Role
) -> List[TicketAttachment]:
    """Returns all attachments associated with a ticket."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )
    if not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for ticket '{ticket_id}'.",
        )
    return (
        db.query(TicketAttachment)
        .filter(TicketAttachment.ticket_id == ticket.ticket_id)
        .order_by(TicketAttachment.created_at.desc())
        .all()
    )


def get_ticket_attachment_detail(
    db: Session, ticket_id: str, attachment_id: str, current_user: User, caller_role: Role
) -> TicketAttachment:
    """Returns single ticket attachment detail."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found.",
        )
    if not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for ticket '{ticket_id}'.",
        )
    attachment = (
        db.query(TicketAttachment)
        .filter(
            TicketAttachment.ticket_id == ticket.ticket_id,
            TicketAttachment.attachment_id == attachment_id,
        )
        .first()
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment '{attachment_id}' not found for ticket '{ticket_id}'.",
        )
    return attachment
