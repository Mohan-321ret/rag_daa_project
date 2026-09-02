"""
Pydantic schemas for the Context Fusion API (Module 7 – Phase 9).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContextFuseRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: Optional[str] = Field(
        default=None, description="Restrict retrieval to chunks from this document only."
    )


class FusedChunkOut(BaseModel):
    document_id: str
    chunk_index: int
    text: str
    score: float
    source: str
    original_char_count: Optional[int] = None
    compressed_char_count: Optional[int] = None


class ContextFusionStatsOut(BaseModel):
    chunks_in: int
    chars_in: int
    duplicates_removed: int
    chunks_after_dedup: int
    cross_encoder_applied: bool
    chunks_dropped_for_budget: int
    chunks_out: int
    chars_out: int
    compression_ratio: float


class ContextFuseResponse(BaseModel):
    query: str
    retrieval_route: Dict[str, Any]
    stats: ContextFusionStatsOut
    optimized_context: str
    chunks: List[FusedChunkOut]
