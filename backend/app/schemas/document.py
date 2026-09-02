"""
Pydantic schemas for the Document Ingestion API (Module 1).
Separates API contract from ORM model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Upload response ───────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """Returned to the client after a successful document upload."""
    success: bool = True
    document_id: str = Field(..., examples=["DOC_1001"])
    filename: str
    original_filename: str
    document_type: str
    ocr_used: bool
    language: Optional[str] = None         # auto-detected language (Step 3)
    word_count: int
    character_count: int
    extraction_duration_s: Optional[float]
    processing_status: str
    chunk_count: int = 0                   # number of semantic chunks (Step 4+5)
    upload_date: datetime

    # ── Knowledge Evolution (Module 3 – Phase 6) ──────────────────────────────
    version: int = 1                       # document version number
    is_new_version: bool = False           # True if this upload updated an existing doc
    duplicate: bool = False                # True if content was identical → skipped
    previous_version_id: Optional[str] = None
    evolution: Optional[dict] = None       # diff / drift / conflict / reindex summary

    # ── Domain-Aware Document Metadata ────────────────────────────────────────
    department: Optional[str] = None
    domain_id: Optional[str] = None
    domain_key: Optional[str] = None
    visibility: str = "domain"
    permissions: str = "private"
    owner_id: Optional[str] = None
    uploaded_by_id: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Error response ────────────────────────────────────────────────────────────

class DocumentUploadError(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None


# ── Internal data transfer objects ───────────────────────────────────────────

class ExtractedDocumentData(BaseModel):
    """
    Internal DTO passed between services.
    Carries extracted text + metadata before DB persistence.
    """
    # Identity
    document_id: str
    filename: str
    original_filename: str
    document_type: str
    file_extension: str

    # Extracted text
    extracted_text: str
    ocr_used: bool

    # Document metadata (from file properties or defaults)
    author: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None
    permissions: str = "private"
    language: Optional[str] = None

    # Domain-Aware Document Metadata: access-control fields, resolved by the
    # API layer ("Domain Assignment" / "Permission Assignment" pipeline
    # steps) BEFORE this DTO reaches storage_service.
    domain_id: Optional[str] = None
    visibility: str = "domain"
    owner_id: Optional[str] = None
    uploaded_by_id: Optional[str] = None

    # Stats
    word_count: int
    character_count: int
    extraction_duration_s: Optional[float] = None
    upload_date: datetime

    model_config = {"arbitrary_types_allowed": True}
