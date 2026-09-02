"""
Pydantic schemas for the Query Management API (Query Log viewing/export).

Phase 9: Query Logs and Query History Management
Supports role-based filtering and sensitive field masking:
- Employee: own query history only
- Analyst: permitted analytics/query information
- Domain Manager: query info for their domain
- Super Admin / Platform Owner: platform-wide query logs

Provides different schema levels:
- QueryLogListItem: summary for list views
- QueryLogDetail: complete trace with all fields
- QueryLogListResponse: paginated list response
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


class QueryLogListItem(BaseModel):
    """Summary view for query log lists (sensitive fields masked)."""
    query_id: str
    user_id: Optional[str] = None
    query_text: str
    answer_text: Optional[str] = None
    intent: Optional[str] = None
    complexity: Optional[str] = None
    route: Optional[str] = None
    retrieval_strategy: Optional[str] = None
    model_used: Optional[str] = None
    confidence_score: Optional[float] = None
    is_grounded: Optional[bool] = None
    was_rewritten: bool
    hallucinations_detected: int
    retrieved_chunks: int
    citation_count: int
    verification_result: Optional[str] = None
    ticket_status: Optional[str] = None
    latency_ms: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("user_id", mode="before")
    @classmethod
    def _stringify_user_id(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None


class QueryLogDetail(BaseModel):
    """Complete query log with all fields (sensitive fields included for authorized users)."""
    query_id: str
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    user_domain: Optional[str] = None
    query_text: str
    answer_text: Optional[str] = None
    
    # Pipeline decisions
    intent: Optional[str] = None
    complexity: Optional[str] = None
    route: Optional[str] = None
    route_overridden: bool
    retrieval_strategy: Optional[str] = None
    model_used: Optional[str] = None
    document_id_filter: Optional[str] = None
    
    # Retrieval details
    retrieved_chunk_ids: List[str] = []
    authorized_chunk_ids: List[str] = []
    retrieval_score: Optional[float] = None
    reranking_score: Optional[float] = None
    reranking_explanation: Optional[str] = None
    
    # Outcome signals
    confidence_score: Optional[float] = None
    is_grounded: Optional[bool] = None
    was_rewritten: bool
    hallucinations_detected: int
    retrieved_chunks: int
    
    # Citation and verification
    citation_count: int
    verification_result: Optional[str] = None
    verification_details: Optional[str] = None
    
    # Ticket association
    ticket_id: Optional[str] = None
    ticket_status: Optional[str] = None
    
    # Sensitive data (only for authorized users)
    chunk_access_violations: int = 0
    access_violation_details: Optional[str] = None
    
    # Performance
    latency_ms: Optional[float] = None
    retrieval_latency_ms: Optional[float] = None
    reranking_latency_ms: Optional[float] = None
    llm_latency_ms: Optional[float] = None
    
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("user_id", "ticket_id", mode="before")
    @classmethod
    def _stringify_ids(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None


class QueryLogListResponse(BaseModel):
    """Paginated list of query logs with filtering context."""
    total: int
    skip: int
    limit: int
    scope: str  # "own" | "domain" | "global"
    logs: List[QueryLogListItem]


class QueryLogDetailResponse(BaseModel):
    """Single query log detail view."""
    log: QueryLogDetail
    # Additional metadata for detail view
    can_view_sensitive: bool  # whether caller can view sensitive fields


# ── Filter schemas for advanced queries ──────────────────────────────────────
class QueryLogFilterParams(BaseModel):
    """Filter parameters for query log searches."""
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    user_domain: Optional[str] = None
    intent: Optional[str] = None
    route: Optional[str] = None
    retrieval_strategy: Optional[str] = None
    model_used: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    ticket_status: Optional[str] = None
    is_grounded: Optional[bool] = None
    was_rewritten: Optional[bool] = None
    verification_result: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search_text: Optional[str] = None  # searches query_text and answer_text
    
    model_config = {"from_attributes": True}


class QueryLogExportResponse(BaseModel):
    """Batch export response."""
    total_exported: int
    logs: List[QueryLogDetail]
