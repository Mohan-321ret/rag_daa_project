"""
Pydantic schemas for the Enterprise Ticketing System (Phase 10, 11, 12).

Includes schemas for:
- Creating tickets from low-confidence answers
- Listing, searching, and multi-attribute filtering of tickets
- Admin Panel Ticket Dashboard analytics and SLA metrics
- Rich ticket detail with query history, evidence, citations, and conversation context
- Administrative lifecycle action requests (assign, priority, status, resolve, close, notes)
- Domain routing metadata and configuration
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.ticket import (
    RESOLUTION_TYPES,
    ResolutionType,
    TicketPriority,
    TicketStatus,
)


class UserMiniOut(BaseModel):
    """Minimal user representation for assignees and resolvers."""
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v: object) -> str:
        return str(v) if v is not None else ""


class QueryHistoryOut(BaseModel):
    """Summary of the originating query from query_logs."""
    query_id: Optional[str] = None
    query_text: Optional[str] = None
    latency_ms: Optional[float] = None
    search_method: Optional[str] = None
    retrieval_mode: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[datetime] = None


class TicketListItem(BaseModel):
    """Ticket summary for list and dashboard views."""
    ticket_id: str
    query_id: Optional[str] = None
    user_id: Optional[str] = None
    title: Optional[str] = "Support Ticket"
    original_question: Optional[str] = ""
    user_question: Optional[str] = None
    confidence_score: Optional[float] = 0.0
    confidence_threshold: Optional[float] = 0.50
    threshold: Optional[float] = None
    priority: Optional[str] = "medium"
    domain: Optional[str] = None
    status: Optional[str] = "open"
    assigned_to: Optional[str] = None
    assigned_expert: Optional[UserMiniOut] = None
    assigned_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    # Phase 13: Resolution metadata
    resolution_type: Optional[str] = None
    resolved_by: Optional[str] = None
    resolver_user: Optional[UserMiniOut] = None
    # SLA metadata
    is_overdue: bool = False
    sla_hours: int = 72
    sla_due_at: Optional[datetime] = None
    # Phase 11: Domain routing metadata
    routed_domain_id: Optional[str] = None
    routing_confidence: Optional[float] = None
    routing_method: Optional[str] = None
    routing_timestamp: Optional[datetime] = None
    needs_triage: bool = False

    model_config = {"from_attributes": True}

    @field_validator("user_id", "resolved_by", mode="before")
    @classmethod
    def _stringify_user_id(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None

    @field_validator("assigned_to", "routed_domain_id", mode="before")
    @classmethod
    def _stringify_uuid_fields(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None

    @model_validator(mode="after")
    def _populate_aliases_and_sla(self) -> TicketListItem:
        if self.title is None:
            self.title = "Support Ticket"
        if self.original_question is None:
            self.original_question = ""
        if self.confidence_score is None:
            self.confidence_score = 0.0
        if self.confidence_threshold is None:
            self.confidence_threshold = self.threshold or 0.50
        if self.threshold is None:
            self.threshold = self.confidence_threshold
        if self.user_question is None:
            self.user_question = self.original_question
        if self.priority is None:
            self.priority = "medium"
        if self.status is None:
            self.status = "open"
        
        # Calculate SLA
        sla_matrix = {"critical": 24, "high": 48, "medium": 72, "low": 120}
        self.sla_hours = sla_matrix.get(self.priority.lower(), 72)
        if self.created_at:
            due = self.created_at + timedelta(hours=self.sla_hours)
            self.sla_due_at = due
            now = datetime.now(timezone.utc) if self.created_at.tzinfo else datetime.utcnow()
            if self.status not in ("resolved", "closed", "rejected"):
                self.is_overdue = now > due
            else:
                self.is_overdue = False
        return self


class TicketDetail(BaseModel):
    """Complete, enriched ticket information."""
    ticket_id: str
    query_id: Optional[str] = None
    user_id: Optional[str] = None
    title: Optional[str] = "Support Ticket"
    description: Optional[str] = ""
    original_question: Optional[str] = ""
    user_question: Optional[str] = None
    generated_answer: Optional[str] = ""
    confidence_score: Optional[float] = 0.0
    confidence_threshold: Optional[float] = 0.50
    threshold: Optional[float] = None
    evidence: Optional[str] = None
    citations: List[str] = Field(default_factory=list)
    source_document_ids: List[str] = Field(default_factory=list)
    priority: Optional[str] = "medium"
    domain: Optional[str] = None
    status: Optional[str] = "open"
    assigned_to: Optional[str] = None
    assigned_domain_expert: Optional[UserMiniOut] = None
    assigned_expert: Optional[UserMiniOut] = None
    assigned_at: Optional[datetime] = None
    # Phase 13: Resolution details
    resolution: Optional[str] = None
    resolution_type: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolver_user_id: Optional[str] = None
    resolved_by: Optional[str] = None
    resolver_user: Optional[UserMiniOut] = None
    supporting_evidence: Optional[str] = None
    supporting_document_ids: List[str] = Field(default_factory=list)
    feedback: Optional[str] = None
    internal_notes: Optional[str] = None
    reviewer_notes: Optional[str] = None
    occurrence_count: int = 1
    hallucinations_detected: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # SLA & Overdue metadata
    is_overdue: bool = False
    sla_hours: int = 72
    sla_due_at: Optional[datetime] = None
    elapsed_seconds: Optional[float] = None
    # Associated Query History & Conversation Context
    query_history: Optional[QueryHistoryOut] = None
    conversation_context: Optional[List[Dict[str, Any]]] = None
    # Phase 11: Domain routing metadata
    routed_domain_id: Optional[str] = None
    routing_confidence: Optional[float] = None
    routing_method: Optional[str] = None
    routing_timestamp: Optional[datetime] = None
    needs_triage: bool = False
    # Backward compatibility aliases
    query_text: Optional[str] = None
    answer_text: Optional[str] = None
    department: Optional[str] = None
    corrected_answer: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("user_id", "resolver_user_id", "resolved_by", "assigned_to", "routed_domain_id", mode="before")
    @classmethod
    def _stringify_ids(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None

    @field_validator("source_document_ids", "citations", "supporting_document_ids", mode="before")
    @classmethod
    def _parse_source_docs(cls, v: object) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:
                pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return []

    @model_validator(mode="after")
    def _populate_aliases_and_sla(self) -> TicketDetail:
        if self.threshold is None:
            self.threshold = self.confidence_threshold
        if self.user_question is None:
            self.user_question = self.original_question
        if self.query_text is None:
            self.query_text = self.original_question
        if self.answer_text is None:
            self.answer_text = self.generated_answer
        if self.department is None:
            self.department = self.domain
        if self.internal_notes is None:
            self.internal_notes = self.feedback
        if self.reviewer_notes is None:
            self.reviewer_notes = self.feedback
        if self.corrected_answer is None:
            self.corrected_answer = self.resolution
        if self.resolved_by is None and self.resolver_user_id is not None:
            self.resolved_by = self.resolver_user_id
        elif self.resolver_user_id is None and self.resolved_by is not None:
            self.resolver_user_id = self.resolved_by
        if not self.citations and self.source_document_ids:
            self.citations = list(self.source_document_ids)
        if not self.source_document_ids and self.citations:
            self.source_document_ids = list(self.citations)
        if self.assigned_domain_expert is None and self.assigned_expert is not None:
            self.assigned_domain_expert = self.assigned_expert
        elif self.assigned_expert is None and self.assigned_domain_expert is not None:
            self.assigned_expert = self.assigned_domain_expert

        # Calculate SLA
        sla_matrix = {"critical": 24, "high": 48, "medium": 72, "low": 120}
        self.sla_hours = sla_matrix.get((self.priority or "medium").lower(), 72)
        if self.created_at:
            due = self.created_at + timedelta(hours=self.sla_hours)
            self.sla_due_at = due
            now = datetime.now(timezone.utc) if self.created_at.tzinfo else datetime.utcnow()
            if self.status not in ("resolved", "closed", "rejected"):
                self.is_overdue = now > due
                self.elapsed_seconds = (now - self.created_at).total_seconds()
            else:
                self.is_overdue = False
                if self.resolved_at:
                    self.elapsed_seconds = (self.resolved_at - self.created_at).total_seconds()
        return self


# Backward compatibility alias
TicketOut = TicketDetail


class TicketCreateRequest(BaseModel):
    """Request to manually create a ticket."""
    title: str = Field(..., max_length=512, description="Ticket title")
    description: str = Field(..., description="Detailed description")
    original_question: str = Field(..., description="The user's query")
    generated_answer: str = Field(..., description="The system's answer")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    evidence: Optional[str] = None
    priority: Optional[str] = None
    domain: Optional[str] = None
    query_id: Optional[str] = None
    user_id: Optional[str] = None

    @model_validator(mode="after")
    def _ensure_threshold(self) -> TicketCreateRequest:
        if self.confidence_threshold is None and self.threshold is not None:
            self.confidence_threshold = self.threshold
        elif self.threshold is None and self.confidence_threshold is not None:
            self.threshold = self.confidence_threshold
        elif self.confidence_threshold is None and self.threshold is None:
            self.confidence_threshold = 0.5
            self.threshold = 0.5
        return self


class TicketUpdateRequest(BaseModel):
    """Partial update for ticket status, priority, assignment, and resolution."""
    status: Optional[str] = Field(None, description="New ticket status")
    priority: Optional[str] = Field(None, description="New priority (low, medium, high, critical)")
    assigned_to: Optional[str] = Field(None, description="Assignee user ID or 'unassigned'")
    resolution: Optional[str] = Field(None, description="Resolution details")
    resolution_type: Optional[str] = Field(None, description="Resolution root cause classification")
    supporting_evidence: Optional[str] = Field(None, description="Domain expert supporting evidence note")
    supporting_document_ids: Optional[List[str]] = Field(None, description="Authorized supporting document IDs")
    feedback: Optional[str] = Field(None, description="Resolver's notes/internal feedback")
    internal_notes: Optional[str] = Field(None, description="Alias for feedback")
    reviewer_notes: Optional[str] = Field(None, description="Alias for feedback")
    corrected_answer: Optional[str] = Field(None, description="Alias for resolution")

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            normalized = v.strip().lower()
            if normalized == "dismissed":
                normalized = "rejected"
            valid_statuses = [s.value.lower() for s in TicketStatus]
            if normalized not in valid_statuses:
                raise ValueError(f"status must be one of {valid_statuses}")
            return normalized
        return v

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            normalized = v.strip().lower()
            valid_priorities = [p.value.lower() for p in TicketPriority]
            if normalized not in valid_priorities:
                raise ValueError(f"priority must be one of {valid_priorities}")
            return normalized
        return v

    @field_validator("resolution_type")
    @classmethod
    def _valid_resolution_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            normalized = v.strip().upper()
            if normalized not in RESOLUTION_TYPES:
                raise ValueError(f"resolution_type must be one of {RESOLUTION_TYPES}")
            return normalized
        return v

    @model_validator(mode="after")
    def _sync_aliases(self) -> TicketUpdateRequest:
        if self.feedback is None:
            if self.internal_notes is not None:
                self.feedback = self.internal_notes
            elif self.reviewer_notes is not None:
                self.feedback = self.reviewer_notes
        if self.resolution is None and self.corrected_answer is not None:
            self.resolution = self.corrected_answer
        return self


# ── Action Request Schemas for Dedicated Endpoints ────────────────────────────

class TicketAssignActionRequest(BaseModel):
    """Request to assign or reassign a ticket to a domain expert."""
    assigned_to: str = Field(..., description="User ID of the assigned domain expert (or 'unassigned')")
    notes: Optional[str] = Field(None, description="Optional assignment notes")


class TicketPriorityActionRequest(BaseModel):
    """Request to change a ticket's priority level."""
    priority: str = Field(..., description="New priority level (low, medium, high, critical)")
    notes: Optional[str] = Field(None, description="Reason for priority change")

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in [p.value.lower() for p in TicketPriority]:
            raise ValueError(f"priority must be one of {[p.value for p in TicketPriority]}")
        return norm


class TicketStatusActionRequest(BaseModel):
    """Request to change ticket lifecycle status."""
    status: str = Field(..., description="New lifecycle status")
    notes: Optional[str] = Field(None, description="Optional status change notes")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm == "dismissed":
            norm = "rejected"
        if norm not in [s.value.lower() for s in TicketStatus]:
            raise ValueError(f"status must be one of {[s.value for s in TicketStatus]}")
        return norm


class TicketResolveActionRequest(BaseModel):
    """Request to resolve a support ticket with domain expert verified answer (Phase 13)."""
    resolution: str = Field(
        ..., min_length=3, description="Verified domain expert resolution / corrected answer text"
    )
    resolution_type: str = Field(
        ...,
        description="Root cause classification: KNOWLEDGE_MISSING, RETRIEVAL_FAILURE, INCORRECT_GENERATION, OUTDATED_DOCUMENT, ACCESS_RESTRICTION, DOCUMENT_CONFLICT, USER_CLARIFICATION, OTHER",
    )
    internal_notes: Optional[str] = Field(
        None, description="Optional internal reviewer notes or rationale"
    )
    supporting_evidence: Optional[str] = Field(
        None, description="Optional supporting evidence note or citation explanation"
    )
    supporting_document_ids: Optional[List[str]] = Field(
        None, description="Optional authorized supporting document IDs"
    )

    @field_validator("resolution_type")
    @classmethod
    def _validate_res_type(cls, v: str) -> str:
        norm = v.strip().upper()
        if norm not in RESOLUTION_TYPES:
            raise ValueError(f"resolution_type must be one of {RESOLUTION_TYPES}")
        return norm


class TicketCloseActionRequest(BaseModel):
    """Request to close a support ticket."""
    feedback: Optional[str] = Field(None, description="Closing summary or notes")


class TicketNotesActionRequest(BaseModel):
    """Request to append internal triage notes."""
    notes: str = Field(..., description="Internal note text to append to the ticket")


# ── List & Dashboard Response Schemas ─────────────────────────────────────────

class TicketListResponse(BaseModel):
    """Paginated list of tickets with total count."""
    total: int
    skip: int
    limit: int
    tickets: List[TicketListItem]


class TicketDashboardResponse(BaseModel):
    """Admin Panel Ticket Dashboard Analytics & Metrics."""
    total_tickets: int
    open_tickets: int
    unassigned_tickets: int
    in_progress_tickets: int
    resolved_tickets: int
    closed_tickets: int
    overdue_tickets: int
    low_confidence_ticket_count: int
    avg_resolution_time_seconds: Optional[float] = None
    avg_resolution_time_hours: Optional[float] = None
    # Granular status breakdown
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_domain: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)
    by_routing_method: Dict[str, int] = Field(default_factory=dict)
    by_resolution_type: Dict[str, int] = Field(default_factory=dict)
    avg_confidence_open: Optional[float] = None
    avg_confidence_all: Optional[float] = None


class TicketStatsResponse(BaseModel):
    """Legacy Ticket statistics by status."""
    total: int
    open: int
    needs_triage: int = 0
    routed: int = 0
    assigned: int = 0
    in_progress: int = 0
    resolved: int = 0
    closed: int = 0
    rejected: int = 0
    unassigned_tickets: int = 0
    overdue_tickets: int = 0
    low_confidence_ticket_count: int = 0
    by_domain: Dict[str, int] = Field(default_factory=dict)
    by_department: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)
    by_routing_method: Dict[str, int] = Field(default_factory=dict)
    by_resolution_type: Dict[str, int] = Field(default_factory=dict)
    avg_confidence_open: Optional[float] = None
    avg_confidence_all: Optional[float] = None
    avg_resolution_time_hours: Optional[float] = None
    avg_resolution_time_seconds: Optional[float] = None


class TicketResponse(BaseModel):
    """Ticket response with appropriate field visibility."""
    ticket: TicketDetail


class TicketUserNotification(BaseModel):
    """User-friendly message when ticket is created."""
    message: str = Field(
        ...,
        description="User-friendly message (no system details exposed)"
    )
    ticket_id: Optional[str] = Field(
        None,
        description="Ticket ID for reference (optional)"
    )
    support_message: Optional[str] = Field(
        None,
        description="Additional support instructions"
    )


class TicketConfigResponse(BaseModel):
    """Current ticketing system configuration."""
    ticketing_enabled: bool
    ticket_confidence_threshold: float
    threshold: float
    ticket_default_priority: str
    ticket_default_domain: str
    priority_cutoffs: Dict[str, float]
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class TicketConfigUpdateRequest(BaseModel):
    """Request to update ticketing configuration (Admin only)."""
    ticket_confidence_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Minimum confidence score to avoid ticket creation (0.0 - 1.0)"
    )
    threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Alias for ticket_confidence_threshold"
    )
    ticketing_enabled: Optional[bool] = Field(
        None, description="Master enable/disable switch for automatic ticketing"
    )
    ticket_default_priority: Optional[str] = Field(
        None, description="Default priority when confidence gap calculation is not used"
    )
    ticket_default_domain: Optional[str] = Field(
        None, description="Default fallback domain for tickets"
    )

    @model_validator(mode="after")
    def _sync_threshold(self) -> TicketConfigUpdateRequest:
        if self.ticket_confidence_threshold is None and self.threshold is not None:
            self.ticket_confidence_threshold = self.threshold
        elif self.threshold is None and self.ticket_confidence_threshold is not None:
            self.threshold = self.ticket_confidence_threshold
        return self
