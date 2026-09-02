"""
Pydantic schemas for Phase 15: Ticketing ↔ Continuous Learning.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Learning Signal Schemas ───────────────────────────────────────────────────

class LearningSignalOut(BaseModel):
    signal_id: str
    signal_type: str
    query_id: Optional[str] = None
    ticket_id: Optional[str] = None
    feedback_id: Optional[str] = None
    domain_id: Optional[str] = None
    confidence_score: Optional[float] = None
    was_correct: Optional[str] = None
    retrieval_route: Optional[str] = None
    intent: Optional[str] = None
    resolution_type: Optional[str] = None
    details: Optional[str] = None     # JSON string
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    signals: List[LearningSignalOut]
    signal_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts of each signal type in the current window",
    )


# ── Threshold History Schemas ─────────────────────────────────────────────────

class ThresholdHistoryOut(BaseModel):
    history_id: str
    metric_name: str
    old_value: Optional[float] = None
    new_value: float
    reason: str
    supporting_data: Optional[str] = None   # JSON string
    source: str      # "auto_suggestion" | "admin_applied"
    approved_by: Optional[str] = None
    applied_at: Optional[datetime] = None
    suggestion_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("approved_by", "suggestion_id", mode="before")
    @classmethod
    def coerce_to_str(cls, v: Any) -> Optional[str]:
        """Coerce UUID / numeric objects to str; leave None as-is."""
        if v is None:
            return None
        return str(v)


class ThresholdApplyRequest(BaseModel):
    suggestion_id: str = Field(
        ...,
        description="history_id of the auto_suggestion row to apply",
        examples=["THR_A1B2C3D4E5"],
    )


class ThresholdApplyResponse(BaseModel):
    applied_history_id: str
    metric_name: str
    old_value: Optional[float]
    new_value: float
    applied_by: str
    message: str


class PendingSuggestionOut(BaseModel):
    history_id: str
    metric_name: str
    current_value: float
    suggested_value: float
    reason: str
    supporting_data: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Extended Metrics Schemas ──────────────────────────────────────────────────

class ConfidenceCalibrationBucket(BaseModel):
    bucket_min: float
    bucket_max: float
    predicted_midpoint: float
    total: int
    correct: int
    partial: int
    incorrect: int
    actual_correctness_rate: float


class ExtendedMetricsResponse(BaseModel):
    """Full 8-metric Phase 15 response."""
    window_days: Optional[int] = None

    # ── Phase 12: Original 4 metrics ─────────────────────────────────────────
    total_queries: int
    total_rated: int
    user_satisfaction: Optional[float] = Field(
        default=None, description="Share of 👍 among ALL rated queries (0..1)."
    )
    hallucination_rate: Optional[float] = Field(
        default=None,
        description="Share of queries where Evidence Verification flagged a hallucination.",
    )
    avg_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    queries_by_route: Dict[str, int] = Field(default_factory=dict)
    retrieval_accuracy_by_route: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Share of 👍 among rated queries, per retrieval route.",
    )
    samples_by_route: Dict[str, int] = Field(default_factory=dict)

    # ── Phase 15: 4 new metrics ────────────────────────────────────────────────
    ticket_generation_rate: Optional[float] = Field(
        default=None,
        description="Tickets auto-generated / total queries (0..1).",
    )
    ticket_resolution_rate: Optional[float] = Field(
        default=None,
        description="Resolved+closed tickets / total tickets in window (0..1).",
    )
    domain_routing_accuracy: Optional[float] = Field(
        default=None,
        description="% of routed tickets NOT flagged as routing_error (0..1).",
    )
    avg_ticket_resolution_time_hours: Optional[float] = Field(
        default=None,
        description="Average hours from ticket creation to resolution.",
    )
    total_tickets: int = 0
    resolved_tickets: int = 0
    signal_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of each learning signal type in the window.",
    )


# ── Improvement Report Schema ─────────────────────────────────────────────────

class RetrievalFailurePatternOut(BaseModel):
    route: str
    intent: Optional[str] = None
    failure_count: int
    total_signals: int
    failure_rate: float


class DomainRoutingStatsOut(BaseModel):
    total_routed: int
    routing_errors: int
    accuracy: Optional[float] = None
    error_rate: Optional[float] = None
    needs_triage_count: int


class ImprovementReportResponse(BaseModel):
    window_days: Optional[int] = None
    domain_routing: DomainRoutingStatsOut
    retrieval_failure_patterns: List[RetrievalFailurePatternOut] = Field(default_factory=list)
    route_satisfaction: Dict[str, Any] = Field(default_factory=dict)
    learning_settings: Dict[str, Any] = Field(default_factory=dict)
