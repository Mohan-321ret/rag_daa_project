"""
Ticket ORM Model  –  Phase 10/11: Enterprise Ticketing + Domain Routing
------------------------------------------------------------------------
Represents the `tickets` table: one row per support ticket generated from
low-confidence RAG answers. Tracks the complete lifecycle from creation through
resolution, including assignee history, priority levels, and resolution notes.

Phase 11 adds domain-based routing columns:
- routed_domain_id: FK to the domain this ticket was classified into
- routing_confidence: how confident the classifier was (0.0–1.0)
- routing_method: which strategy determined the domain
- routing_timestamp: when the routing decision was made
- needs_triage: flag for uncertain classifications

Used by:
- RAG pipeline: Auto-generate when confidence_score < threshold
- Domain router: Classify and route to appropriate domain queue
- Admin panel: Ticket management and routing
- Query logs: Link queries to their associated tickets
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, Sequence, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, synonym

from app.db.database import Base


class TicketStatus(str, Enum):
    """Valid ticket lifecycle statuses."""
    OPEN = "open"              # Newly created, waiting for routing
    NEEDS_TRIAGE = "needs_triage"  # Domain uncertain, awaiting admin triage
    ROUTED = "routed"          # Assigned to a domain/team
    ASSIGNED = "assigned"      # Assigned to specific person
    IN_PROGRESS = "in_progress"  # Being actively reviewed
    IN_REVIEW = "in_review"    # Alias for review state
    RESOLVED = "resolved"      # Solution found, waiting for closure
    REOPENED = "reopened"      # Previously resolved ticket returned to active work
    CLOSED = "closed"          # Closed after confirmation
    REJECTED = "rejected"      # Not a real issue, dismissed


TICKET_STATUSES = [s.value for s in TicketStatus]


class TicketPriority(str, Enum):
    """Ticket priority levels based on confidence gap."""
    LOW = "low"                    # 0.8-0.9 (minor confidence gap)
    MEDIUM = "medium"              # 0.6-0.8 (moderate concern)
    HIGH = "high"                  # 0.4-0.6 (significant concern)
    CRITICAL = "critical"          # <0.4 (very low confidence)


class ResolutionFormat(str, Enum):
    """How the ticket resolution is supplied, separate from its root cause."""
    TEXT = "TEXT"
    FILE = "FILE"
    BOTH = "BOTH"


RESOLUTION_FORMATS = [value.value for value in ResolutionFormat]


ticket_number_sequence = Sequence("tickets_ticket_number_seq", metadata=Base.metadata)

ticket_documents = Table(
    "ticket_documents",
    Base.metadata,
    Column("ticket_id", UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", String(64), ForeignKey("documents.document_id", ondelete="CASCADE"), primary_key=True),
)


class ResolutionType(str, Enum):
    """
    Standard resolution root cause classifications for domain expert ticket resolution (Phase 13).
    """
    KNOWLEDGE_MISSING = "KNOWLEDGE_MISSING"          # Information not present in knowledge base
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"          # Relevant docs in KB, but retrieval missed them
    INCORRECT_GENERATION = "INCORRECT_GENERATION"    # Retrieval was good, but LLM hallucinated / answered wrong
    OUTDATED_DOCUMENT = "OUTDATED_DOCUMENT"          # Document in KB is outdated / superseded
    ACCESS_RESTRICTION = "ACCESS_RESTRICTION"        # User lacks required permissions for the authoritative docs
    DOCUMENT_CONFLICT = "DOCUMENT_CONFLICT"          # Inconsistency between multiple documents in KB
    USER_CLARIFICATION = "USER_CLARIFICATION"        # Query was ambiguous or needed user clarification
    OTHER = "OTHER"                                  # Other root cause


RESOLUTION_TYPES = [r.value for r in ResolutionType]


class Ticket(Base):
    """Maps to the `tickets` table (one row per support ticket)."""

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "resolution_format IS NULL OR resolution_format IN ('TEXT', 'FILE', 'BOTH')",
            name="ck_tickets_resolution_format",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # ── Ticket Identity ──────────────────────────────────────────────────────
    ticket_id = Column(String(64), unique=True, nullable=False, index=True)  # TKT_xxxx
    ticket_number = Column(
        Integer,
        ticket_number_sequence,
        nullable=False,
        unique=True,
        server_default=ticket_number_sequence.next_value(),
    )
    
    # ── Origin (Link to Query Logs) ──────────────────────────────────────────
    query_id = Column(String(64), nullable=True, index=True)  # Reference to query_logs.query_id
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # ── Ticket Content ───────────────────────────────────────────────────────
    title = Column(String(512), nullable=False)  # Brief summary
    description = Column(Text, nullable=False)   # Detailed description
    
    # ── Query Context ────────────────────────────────────────────────────────
    user_query = Column(Text, nullable=False)  # The user's query
    generated_answer = Column(Text, nullable=False)   # The system's answer
    
    # ── Confidence & Verification ────────────────────────────────────────────
    confidence_score = Column(Float, nullable=False)  # Why ticket was created
    confidence_threshold = Column(Float, nullable=False)  # Threshold that triggered ticket
    evidence = Column(Text, nullable=True)  # Why low confidence? Explanation
    
    # ── Priority & Assignment ────────────────────────────────────────────────
    priority = Column(String(16), nullable=False, default=TicketPriority.MEDIUM.value, index=True)
    domain = Column(String(256), nullable=True, index=True)  # Organizational domain (legacy free-text)
    status = Column(
        String(32), 
        nullable=False, 
        default=TicketStatus.OPEN.value, 
        index=True
    )
    
    # ── Domain Routing (Phase 11) ────────────────────────────────────────────
    routed_domain_id = Column(
        UUID(as_uuid=True),
        ForeignKey("domains.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # FK to the domain this ticket was routed to
    routed_domain = relationship(
        "Domain", back_populates="routed_tickets", foreign_keys=[routed_domain_id]
    )
    routing_confidence = Column(Float, nullable=True)  # 0.0–1.0 classification confidence
    routing_method = Column(String(32), nullable=True)  # user_selected | user_domain | intent | ner | document_domain | llm_fallback | needs_triage
    routing_timestamp = Column(DateTime(timezone=True), nullable=True)  # When routing decision was made
    needs_triage = Column(Boolean, nullable=False, default=False)  # True if domain uncertain
    
    # ── Assignment ───────────────────────────────────────────────────────────
    assigned_to = Column(String(256), nullable=True, index=True)  # User ID / Assignee
    assigned_manager_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user = relationship("User", back_populates="requested_tickets", foreign_keys=[user_id])
    assigned_manager = relationship(
        "User", back_populates="managed_tickets", foreign_keys=[assigned_manager_id]
    )
    documents = relationship("Document", secondary=ticket_documents, back_populates="tickets")
    assigned_at = Column(DateTime(timezone=True), nullable=True)  # When assigned
    
    # ── Resolution (Phase 13: Domain Expert Resolution) ───────────────────────
    resolution = Column(Text, nullable=True)  # How was it resolved? (Verified answer)
    resolution_type = Column(String(64), nullable=True, index=True)  # Root cause classification
    resolution_format = Column(String(8), nullable=True)  # TEXT | FILE | BOTH
    resolved_at = Column(DateTime(timezone=True), nullable=True)  # When resolved
    resolver_user_id = Column(UUID(as_uuid=True), nullable=True)  # Who resolved it
    supporting_evidence = Column(Text, nullable=True)  # Domain expert supporting evidence explanation
    supporting_document_ids = Column(Text, nullable=True)  # JSON or comma-separated authorized supporting docs
    
    # ── Feedback ─────────────────────────────────────────────────────────────
    feedback = Column(Text, nullable=True)  # Resolver's notes/feedback
    
    # ── Deduplication & Diagnostics (Legacy & Extended) ───────────────────────
    occurrence_count = Column(Integer, nullable=False, default=1)  # How many times this issue occurred
    source_document_ids = Column(Text, nullable=True)  # JSON or comma-separated document IDs
    source_chunks = Column(Text, nullable=True)  # JSON list of retrieved source chunks
    hallucinations_detected = Column(Integer, nullable=True, default=0)  # Number of unverified claims
    
    # ── Audit ────────────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # ── Synonym Aliases & Backward Compatibility ──────────────────────────────
    threshold = synonym("confidence_threshold")
    original_question = synonym("user_query")
    query_text = synonym("user_query")
    answer_text = synonym("generated_answer")
    department = synonym("domain")
    raised_by_user_id = synonym("user_id")
    reviewer_notes = synonym("feedback")
    internal_notes = synonym("feedback")
    corrected_answer = synonym("resolution")
    resolved_by = synonym("resolver_user_id")

    # Priority-based SLA turnaround hours
    SLA_HOURS = {
        TicketPriority.CRITICAL.value: 24,
        TicketPriority.HIGH.value: 48,
        TicketPriority.MEDIUM.value: 72,
        TicketPriority.LOW.value: 120,
    }

    @property
    def sla_hours(self) -> int:
        return self.SLA_HOURS.get((self.priority or "medium").lower(), 72)

    @property
    def is_overdue(self) -> bool:
        if self.status in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value, TicketStatus.REJECTED.value):
            return False
        if not self.created_at:
            return False
        from datetime import timedelta
        due_at = self.created_at + timedelta(hours=self.sla_hours)
        now = datetime.now(timezone.utc)
        if self.created_at.tzinfo is None:
            now = datetime.utcnow()
        return now > due_at

    def __repr__(self) -> str:
        return f"<Ticket(ticket_id='{self.ticket_id}', domain='{self.domain}', priority='{self.priority}', status='{self.status}')>"
