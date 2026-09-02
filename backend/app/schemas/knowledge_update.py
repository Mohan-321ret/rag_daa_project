"""
Knowledge Update Request Schemas — Phase 14: Ticket-Driven Knowledge Evolution
------------------------------------------------------------------------------
Pydantic schemas for creating, listing, reviewing, and applying knowledge update
recommendations staged from resolved support tickets.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.models.knowledge_update_request import (
    KNOWLEDGE_UPDATE_STATUSES,
    KnowledgeUpdateStatus,
)
from app.models.ticket import RESOLUTION_TYPES


class UserMiniInfo(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class KnowledgeUpdateRequestCreate(BaseModel):
    """Payload to stage a Knowledge Update Request from a ticket."""
    ticket_id: str = Field(..., description="Originating Ticket ID (e.g. TKT_...)")
    document_id: Optional[str] = Field(None, description="Target document ID if updating existing document")
    target_filename: Optional[str] = Field(None, description="Target filename for version lineage matching")
    domain: Optional[str] = Field(None, description="Target domain key (e.g. 'hr', 'finance')")
    root_cause: Optional[str] = Field("OTHER", description="Root cause classification")
    title: str = Field(..., min_length=3, max_length=256, description="Descriptive summary of knowledge update")
    description: Optional[str] = Field(None, description="Detailed explanation/context from ticket")
    suggested_resolution: str = Field(..., min_length=3, description="Verified domain expert answer")
    supporting_evidence: Optional[str] = Field(None, description="Supporting evidence / policy references")
    supporting_document_ids: Optional[List[str]] = Field(default_factory=list, description="Referenced document IDs")

    @field_validator("root_cause")
    @classmethod
    def validate_root_cause(cls, v: Optional[str]) -> str:
        if not v:
            return "OTHER"
        norm = v.strip().upper()
        if norm not in RESOLUTION_TYPES:
            return "OTHER"
        return norm


class KnowledgeUpdateRequestReview(BaseModel):
    """Payload for Administrator approval or rejection."""
    action: str = Field(..., description="'approve' or 'reject'")
    admin_notes: Optional[str] = Field(None, description="Optional review rationale or rejection feedback")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in ("approve", "reject", "cancel"):
            raise ValueError("action must be 'approve', 'reject', or 'cancel'")
        return norm


class KnowledgeUpdateRequestApply(BaseModel):
    """Payload for Administrator applying an approved knowledge update."""
    updated_text: str = Field(..., min_length=5, description="Full authoritative updated text content")
    target_filename: Optional[str] = Field(None, description="Filename for version lineage matching (e.g. 'remote_policy.txt')")
    language_hint: Optional[str] = Field("en", description="Language hint")
    admin_notes: Optional[str] = Field(None, description="Execution notes")


class KnowledgeUpdateRequestOut(BaseModel):
    """Detailed representation of a Knowledge Update Request."""
    id: str
    request_id: str
    ticket_id: str
    document_id: Optional[str] = None
    target_filename: Optional[str] = None
    domain: Optional[str] = None
    root_cause: str
    title: str
    description: Optional[str] = None
    suggested_resolution: str
    supporting_evidence: Optional[str] = None
    supporting_document_ids: List[str] = Field(default_factory=list)
    status: str
    created_by_id: Optional[str] = None
    reviewed_by_id: Optional[str] = None
    created_by: Optional[UserMiniInfo] = None
    reviewed_by: Optional[UserMiniInfo] = None
    reviewed_at: Optional[datetime] = None
    admin_notes: Optional[str] = None
    applied_document_id: Optional[str] = None
    change_event_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("supporting_document_ids", mode="before")
    @classmethod
    def parse_doc_ids(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:
                return [s.strip() for s in v.split(",") if s.strip()]
        return []

    @field_validator("id", "created_by_id", "reviewed_by_id", mode="before")
    @classmethod
    def parse_uuid(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else None


class KnowledgeUpdateRequestListResponse(BaseModel):
    """Paginated list of knowledge update requests."""
    total: int
    skip: int
    limit: int
    requests: List[KnowledgeUpdateRequestOut]


class KnowledgeUpdateStatsResponse(BaseModel):
    """Queue statistics for administrator review."""
    total: int
    pending_review: int
    approved: int
    rejected: int
    applied: int
    cancelled: int
    by_root_cause: Dict[str, int] = Field(default_factory=dict)
    by_domain: Dict[str, int] = Field(default_factory=dict)
