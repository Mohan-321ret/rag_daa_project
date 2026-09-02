"""
Pydantic schemas for the Adaptive Retrieval Engine API (Module 6 – Phase 8).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RetrievalRouteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: Optional[str] = Field(
        default=None, description="Restrict retrieval to chunks from this document only."
    )


class RouteDecisionOut(BaseModel):
    route: str              # vector | bm25 | graph | hybrid
    reason: str
    signals: List[str]


class RetrievedChunkOut(BaseModel):
    document_id: str
    chunk_index: int
    text_preview: str
    score: float
    source: str              # vector | bm25 | graph | "vector+bm25" (hybrid) etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalRouteResponse(BaseModel):
    query: str
    route: RouteDecisionOut
    route_counts: Dict[str, int]
    results: List[RetrievedChunkOut]
