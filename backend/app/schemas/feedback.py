"""
Pydantic schemas for the Continuous Learning API (Module 10 – Phase 12/15).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Collect / Store ─────────────────────────────────────────────────────────

class FeedbackSubmitRequest(BaseModel):
    query_id: str = Field(..., examples=["QRY_3F2A1B9C4D"])
    rating: Literal["up", "down"]
    correction_text: Optional[str] = Field(
        default=None, max_length=4096,
        description="Optional free-text correction (e.g. the right answer), stored for review.",
    )
    # ── Phase 15 fields ───────────────────────────────────────────────────────
    ticket_id: Optional[str] = Field(
        default=None,
        description="ticket_id of the ticket associated with this query (if any).",
    )
    domain_routing_correct: Optional[bool] = Field(
        default=None,
        description="True = user confirms routing was correct; False = wrong domain was assigned.",
    )
    retrieval_failure_flagged: Optional[bool] = Field(
        default=None,
        description="True = user flags that retrieved content was wrong or irrelevant.",
    )


class FeedbackSubmitResponse(BaseModel):
    feedback_id: str
    query_id: str
    rating: str
    message: str


class FeedbackOut(BaseModel):
    feedback_id: str
    query_id: str
    rating: str
    correction_text: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Performance Metrics ───────────────────────────────────────────────────────

class MetricsResponse(BaseModel):
    window_days: Optional[int] = None
    total_queries: int
    total_rated: int
    user_satisfaction: Optional[float] = Field(
        default=None, description="Share of 👍 among ALL rated queries (0..1)."
    )
    hallucination_rate: Optional[float] = Field(
        default=None, description="Share of queries where Evidence Verification flagged a hallucination."
    )
    avg_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    queries_by_route: Dict[str, int] = Field(default_factory=dict)
    retrieval_accuracy_by_route: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Share of 👍 among rated queries, per retrieval route — what Improve Routing acts on.",
    )
    samples_by_route: Dict[str, int] = Field(default_factory=dict)
