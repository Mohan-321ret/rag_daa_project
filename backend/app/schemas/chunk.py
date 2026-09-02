"""
Chunk Pydantic Schemas  –  Phase 3 Module 2
--------------------------------------------
API request/response schemas for the chunks endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChunkOut(BaseModel):
    """API response schema for a single document chunk."""
    id: UUID
    document_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    word_count: int
    faiss_id: Optional[int] = None
    # Domain-aware traceability — copied from the parent Document at write
    # time (see StorageService.save_chunks); a chunk carries its own access
    # context without requiring a JOIN back to `documents`.
    document_version: Optional[int] = None
    domain_id: Optional[str] = None
    visibility: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("domain_id", mode="before")
    @classmethod
    def _stringify_domain_id(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None


class ChunkListResponse(BaseModel):
    """Paginated list of chunks for a document."""
    document_id: str
    total: int
    chunks: List[ChunkOut]


class ChunkSearchResponse(BaseModel):
    """Response from a semantic vector search (returns chunk hits)."""
    query: str
    total_indexed: int
    results: List[dict]   # raw FAISS search results with score + metadata
