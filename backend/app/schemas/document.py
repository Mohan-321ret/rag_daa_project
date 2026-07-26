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
    word_count: int
    character_count: int
    extraction_duration_s: Optional[float]
    processing_status: str
    upload_date: datetime

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

    # Stats
    word_count: int
    character_count: int
    extraction_duration_s: Optional[float] = None
    upload_date: datetime

    model_config = {"arbitrary_types_allowed": True}
