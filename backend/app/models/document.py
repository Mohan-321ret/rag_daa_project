"""
Document ORM Model
------------------
Represents the `documents` table in PostgreSQL.
Stores extracted text, metadata, and processing status.
Original document files are NEVER stored here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base

# Document.visibility values (User/Domain/Access Management — Domain-Aware
# Document Metadata phase). Governs WHO can see a document, distinct from
# the legacy free-text `permissions` label (kept for backward compatibility
# — see that column's own comment below).
DOCUMENT_VISIBILITIES = ("global", "domain", "restricted")


class Document(Base):
    """
    Maps to the `documents` table.

    Columns:
    - document_id   : human-readable ID (DOC_xxxx)
    - filename      : sanitised filename used internally
    - original_filename: original name as uploaded by the user
    - document_type : PDF | DOCX | TXT | HTML | PPTX
    - file_extension: lowercase extension (.pdf, .docx, …)
    - author        : extracted from doc metadata (nullable)
    - title         : extracted from doc metadata (nullable)
    - department    : user-supplied, free-text organizational label (nullable)
    - domain_id     : FK -> domains.id. The access-control-relevant
                      organizational unit (see app/models/domain.py) — NOT
                      the same thing as `department`. Mandatory at the
                      application level unless visibility="global" (enforced
                      in app/api/documents.py, not a DB constraint, since a
                      global document legitimately has none).
    - visibility    : one of DOCUMENT_VISIBILITIES — global (everyone) |
                      domain (same-domain members) | restricted (owner/
                      uploader + explicit grants only — see
                      app/models/document_access.py). This is the field that
                      actually governs document-registry read access
                      (app/services/document_access_service.py); it does NOT
                      yet gate RAG retrieval/chunk search — that's a later
                      phase, documented in this project's permission matrix.
    - permissions   : LEGACY free-text label (default "private"), predates
                      `visibility`. Kept for backward compatibility with
                      existing rows/UI; no longer the field that drives
                      access decisions.
    - owner_id      : FK -> users.id. The document's steward — defaults to
                      the uploader at creation, may be reassigned later.
    - uploaded_by_id: FK -> users.id. Who physically performed the upload.
                      Immutable history, unlike owner_id.
    - language      : detected/user-supplied (nullable)
    - upload_date   : UTC timestamp of the upload
    - ocr_used      : whether Tesseract OCR was invoked
    - word_count    : number of words in extracted text
    - character_count: number of characters in extracted text
    - extracted_text: full cleaned text content
    - processing_status: indexed | failed | processing (fulfills the "status"
                      field named in the Domain-Aware Document Metadata spec)
    - extraction_duration_s: time in seconds for text extraction
    - created_at    : row creation timestamp
    - updated_at    : row last-updated timestamp
    """

    __tablename__ = "documents"

    # ── Primary key ──────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # ── Document identity ─────────────────────────────────────────────────────
    document_id = Column(String(64), unique=True, nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    document_type = Column(String(16), nullable=False)   # PDF, DOCX, TXT …
    file_extension = Column(String(16), nullable=False)  # .pdf, .docx …

    # ── User / document metadata ──────────────────────────────────────────────
    author = Column(String(256), nullable=True)
    title = Column(String(512), nullable=True)
    department = Column(String(256), nullable=True)
    permissions = Column(String(64), nullable=False, default="private")
    language = Column(String(64), nullable=True)

    # ── Domain-aware access metadata ────────────────────────────────────────────
    domain_id = Column(UUID(as_uuid=True), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True, index=True)
    visibility = Column(String(16), nullable=False, default="domain", server_default="domain")
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    upload_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Versioning (Module 3 – Phase 6 Knowledge Evolution) ───────────────────
    content_hash = Column(String(64), nullable=True, index=True)   # SHA-256 of extracted_text
    version = Column(Integer, nullable=False, default=1)
    previous_version_id = Column(String(64), nullable=True)        # document_id of prior version
    is_latest = Column(Boolean, nullable=False, default=True)

    # ── Processing stats ──────────────────────────────────────────────────────
    ocr_used = Column(Boolean, nullable=False, default=False)
    word_count = Column(Integer, nullable=False, default=0)
    character_count = Column(Integer, nullable=False, default=0)
    extraction_duration_s = Column(Float, nullable=True)
    processing_status = Column(
        String(32), nullable=False, default="processing"
    )  # processing | indexed | failed

    # ── Content (TEXT type – unlimited size in PostgreSQL) ────────────────────
    extracted_text = Column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    chunks = relationship(
        "Chunk",
        back_populates="document",
        foreign_keys="Chunk.document_id",
        primaryjoin="Document.document_id == Chunk.document_id",
        cascade="all, delete-orphan",
        lazy="select",
    )
    tickets = relationship("Ticket", secondary="ticket_documents", back_populates="documents")

    def __repr__(self) -> str:
        return (
            f"<Document id={self.document_id!r} "
            f"type={self.document_type!r} "
            f"status={self.processing_status!r}>"
        )
