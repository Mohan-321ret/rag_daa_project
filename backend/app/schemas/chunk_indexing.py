"""
Pydantic schemas for the Chunk Indexing API — Admin Panel: Chunk Indexing
Management. Mirrors app/schemas/ingestion_job.py's shape/conventions.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChunkIndexStatsResponse(BaseModel):
    total_chunks: int
    indexed_chunks: int
    pending_chunks: int
    failed_chunks: int
    stale_chunks: int
    embedding_model: str
    embedding_dimension: int
    index_status: str
    faiss_total_vectors: int
    faiss_active_vectors: int
    last_indexing_time: Optional[datetime] = None


class ChunkInspectOut(BaseModel):
    id: UUID
    document_id: str
    chunk_index: int
    text: str
    word_count: int
    document_version: Optional[int] = None
    domain_id: Optional[str] = None
    visibility: Optional[str] = None
    index_status: str
    faiss_id: Optional[int] = None
    indexed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("domain_id", mode="before")
    @classmethod
    def _stringify_domain_id(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None


class ChunkInspectListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    chunks: List[ChunkInspectOut]


class ReindexErrorEntry(BaseModel):
    ref: str
    error: Optional[str] = None
    at: str


class ReindexJobOut(BaseModel):
    job_id: str
    job_type: str
    status: str
    scope_document_id: Optional[str] = None
    scope_domain_id: Optional[str] = None
    scope_chunk_ids: Optional[List[str]] = None
    total_items: int
    processed_items: int
    failed_items: int
    error_log: List[ReindexErrorEntry] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReindexJobListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    jobs: List[ReindexJobOut]


class ReindexAcceptedResponse(BaseModel):
    success: bool = True
    job_id: str
    job_type: str
    status: str = "queued"
    total_items: int
    message: str = "Reindex job accepted. Processing started in the background."


class ReindexChunksRequest(BaseModel):
    chunk_ids: List[str] = Field(..., min_length=1, description="Chunk row UUIDs to re-index")


class CancelReindexJobResponse(BaseModel):
    success: bool
    job_id: str
    status: str
    message: str
