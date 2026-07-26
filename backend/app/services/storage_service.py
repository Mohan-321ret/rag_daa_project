"""
Storage Service
---------------
Persists the extracted document data (text + metadata) to PostgreSQL.
NEVER stores the original binary file – only text and metadata are saved.
"""
from __future__ import annotations

import logging
from datetime import timezone

from sqlalchemy.orm import Session

from app.models.document import Document
from app.schemas.document import ExtractedDocumentData

logger = logging.getLogger(__name__)


class StorageService:
    """Handles all PostgreSQL persistence for the ingestion pipeline."""

    def __init__(self, db: Session):
        self.db = db

    # ── Create ────────────────────────────────────────────────────────────────

    def save_document(self, data: ExtractedDocumentData) -> Document:
        """
        Persist a new document record to the `documents` table.

        Steps:
        1. Map ExtractedDocumentData → Document ORM model
        2. Add to session
        3. Commit (or rollback on error)
        4. Refresh to get auto-generated fields (id, created_at, etc.)

        Args:
            data: DTO carrying extracted text and metadata.

        Returns:
            The persisted Document ORM object (with DB-generated fields filled in).

        Raises:
            RuntimeError: On any database error.
        """
        logger.info(
            "[StorageService] 💾 Saving document to PostgreSQL | id=%s",
            data.document_id,
        )

        document = Document(
            document_id=data.document_id,
            filename=data.filename,
            original_filename=data.original_filename,
            document_type=data.document_type,
            file_extension=data.file_extension,
            author=data.author,
            title=data.title,
            department=data.department,
            permissions=data.permissions,
            language=data.language,
            upload_date=data.upload_date,
            ocr_used=data.ocr_used,
            word_count=data.word_count,
            character_count=data.character_count,
            extraction_duration_s=data.extraction_duration_s,
            extracted_text=data.extracted_text,
            processing_status="indexed",
        )

        try:
            self.db.add(document)
            self.db.commit()
            self.db.refresh(document)
            logger.info(
                "[StorageService] ✅ Document saved | id=%s words=%d",
                document.document_id, document.word_count,
            )
            return document

        except Exception as exc:
            self.db.rollback()
            logger.error(
                "[StorageService] ❌ DB commit failed for %s: %s",
                data.document_id, exc,
            )
            raise RuntimeError(
                f"Database error while saving document '{data.document_id}': {exc}"
            ) from exc

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_document_id(self, document_id: str) -> Document | None:
        """Fetch a document record by its human-readable document_id."""
        return (
            self.db.query(Document)
            .filter(Document.document_id == document_id)
            .first()
        )

    def list_documents(self, skip: int = 0, limit: int = 50) -> list[Document]:
        """Return a paginated list of all documents."""
        return (
            self.db.query(Document)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    # ── Update status ─────────────────────────────────────────────────────────

    def mark_failed(self, document_id: str, reason: str) -> None:
        """
        Set a document's processing_status to 'failed'.
        Used in the error path to keep an audit trail.
        """
        doc = self.get_by_document_id(document_id)
        if doc:
            doc.processing_status = "failed"
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
