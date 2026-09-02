"""
Continuous Learning API Router  –  Phase 12/15 Module 10
------------------------------------------------------------
Endpoints:
  POST /api/v1/feedback/submit        – Collect a 👍/👎 (+ optional correction + Phase 15 signals)
  GET  /api/v1/feedback/metrics/summary       – Original 4 metrics (Phase 12)
  GET  /api/v1/feedback/metrics/extended      – Full 8 metrics (Phase 15)
  GET  /api/v1/feedback/metrics/confidence-calibration – Calibration buckets
  GET  /api/v1/feedback/{query_id}    – List feedback recorded for one query

Submitting feedback is also what feeds Improve Routing / Improve Retrieval:
once enough ratings accumulate for a route, retrieval_router.py and
adaptive_retrieval_service.py start consulting routing_improvement_service
to escalate underperforming routes to hybrid and widen their retrieval
breadth — see that module's docstring for the mechanism.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.schemas.feedback import (
    FeedbackOut,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    MetricsResponse,
)
from app.schemas.learning import (
    ConfidenceCalibrationBucket,
    ExtendedMetricsResponse,
)
from app.services.auth_service import get_current_user, require_permission
from app.services.feedback_service import get_feedback_for_query, submit_feedback
from app.services.metrics_service import compute_metrics
from app.core.config import settings
from app.core.permissions import Permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["Continuous Learning (Module 10)"])


# ── Collect + Store ────────────────────────────────────────────────────────────

@router.post(
    "/submit",
    response_model=FeedbackSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit 👍/👎 feedback (and an optional correction) for an answer",
    description=(
        "Collect step of Continuous Learning. `query_id` comes from a prior "
        "POST /api/v1/rag/query response. Ratings accumulate into Performance "
        "Metrics and, once there are enough of them, into Improve Routing / "
        "Improve Retrieval decisions for future queries.\n\n"
        "**Phase 15**: Also accepts `ticket_id`, `domain_routing_correct`, and "
        "`retrieval_failure_flagged` to emit richer learning signals."
    ),
)
def submit(
    body: FeedbackSubmitRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FeedbackSubmitResponse:
    try:
        row = submit_feedback(
            db,
            body.query_id,
            body.rating,
            body.correction_text,
            ticket_id=getattr(body, "ticket_id", None),
            domain_routing_correct=getattr(body, "domain_routing_correct", None),
            retrieval_failure_flagged=getattr(body, "retrieval_failure_flagged", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return FeedbackSubmitResponse(
        feedback_id=row.feedback_id,
        query_id=row.query_id,
        rating=row.rating,
        message="Thanks — feedback recorded." + (
            " Correction saved for review." if body.correction_text else ""
        ),
    )


@router.get(
    "/{query_id}",
    response_model=list[FeedbackOut],
    summary="List feedback recorded for one query",
)
def list_feedback(
    query_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.QUERY_LOG_VIEW_GLOBAL)),
) -> list[FeedbackOut]:
    rows = get_feedback_for_query(db, query_id)
    return [FeedbackOut.model_validate(r) for r in rows]


# ── Performance Metrics (Phase 12 — Original 4) ───────────────────────────────

@router.get(
    "/metrics/summary",
    response_model=MetricsResponse,
    summary="Performance Metrics: retrieval accuracy, latency, hallucination rate, satisfaction",
    description=(
        "Aggregates stored QueryLog telemetry + Feedback ratings into the four "
        "tracked metrics, optionally windowed to the last N days and/or "
        "scoped to one retrieval route."
    ),
)
def metrics(
    window_days: Optional[int] = Query(
        default=None, ge=1,
        description=f"Defaults to settings.metrics_default_window_days ({settings.metrics_default_window_days}) if omitted.",
    ),
    route: Optional[str] = Query(default=None, description="Filter to one route: vector|bm25|graph|hybrid"),
    all_time: bool = Query(default=False, description="Ignore the window and aggregate over all time."),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> MetricsResponse:
    effective_window = None if all_time else (window_days or settings.metrics_default_window_days)
    summary = compute_metrics(db, window_days=effective_window, route=route)

    return MetricsResponse(
        window_days=summary.window_days,
        total_queries=summary.total_queries,
        total_rated=summary.total_rated,
        user_satisfaction=summary.user_satisfaction,
        hallucination_rate=summary.hallucination_rate,
        avg_latency_ms=summary.avg_latency_ms,
        p95_latency_ms=summary.p95_latency_ms,
        queries_by_route=summary.queries_by_route,
        retrieval_accuracy_by_route=summary.retrieval_accuracy_by_route,
        samples_by_route=summary.samples_by_route,
    )


# ── Extended Metrics (Phase 15 — All 8 metrics) ───────────────────────────────

@router.get(
    "/metrics/extended",
    response_model=ExtendedMetricsResponse,
    summary="Extended Metrics: all 8 Phase 15 metrics including ticket and routing stats",
    description=(
        "Returns the complete Phase 15 metric set:\n\n"
        "**Original 4 (Phase 12):**\n"
        "- user_satisfaction, hallucination_rate, avg_latency_ms, retrieval_accuracy_by_route\n\n"
        "**New 4 (Phase 15):**\n"
        "- ticket_generation_rate — tickets auto-created / total queries\n"
        "- ticket_resolution_rate — resolved tickets / total tickets\n"
        "- domain_routing_accuracy — % of correctly routed tickets\n"
        "- avg_ticket_resolution_time_hours — mean time from creation to resolution\n\n"
        "Also returns `signal_counts` (breakdown of all learning signal types)."
    ),
    tags=["Continuous Learning (Module 10)", "Phase 15 — Ticketing ↔ Learning"],
)
def extended_metrics(
    window_days: Optional[int] = Query(
        default=None, ge=1,
        description="Lookback window in days. Omit for all-time.",
    ),
    all_time: bool = Query(default=False, description="Override window_days — aggregate over all time."),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> ExtendedMetricsResponse:
    effective_window = None if all_time else (window_days or settings.metrics_default_window_days)
    summary = compute_metrics(db, window_days=effective_window)

    return ExtendedMetricsResponse(
        window_days=summary.window_days,
        total_queries=summary.total_queries,
        total_rated=summary.total_rated,
        user_satisfaction=summary.user_satisfaction,
        hallucination_rate=summary.hallucination_rate,
        avg_latency_ms=summary.avg_latency_ms,
        p95_latency_ms=summary.p95_latency_ms,
        queries_by_route=summary.queries_by_route,
        retrieval_accuracy_by_route=summary.retrieval_accuracy_by_route,
        samples_by_route=summary.samples_by_route,
        ticket_generation_rate=summary.ticket_generation_rate,
        ticket_resolution_rate=summary.ticket_resolution_rate,
        domain_routing_accuracy=summary.domain_routing_accuracy,
        avg_ticket_resolution_time_hours=summary.avg_ticket_resolution_time_hours,
        total_tickets=summary.total_tickets,
        resolved_tickets=summary.resolved_tickets,
        signal_counts=summary.signal_counts,
    )


# ── Confidence Calibration ─────────────────────────────────────────────────────

@router.get(
    "/metrics/confidence-calibration",
    response_model=List[ConfidenceCalibrationBucket],
    summary="Confidence calibration: predicted confidence vs actual correctness",
    description=(
        "Analyzes learning signals to compare predicted confidence buckets "
        "against actual user-confirmed correctness. "
        "Useful for tuning the ticket_confidence_threshold — if the system "
        "reports 0.8 confidence but only 50% of those answers are actually correct, "
        "the threshold should be raised.\n\n"
        "Only includes signals that have both `confidence_score` and `was_correct` set."
    ),
    tags=["Continuous Learning (Module 10)", "Phase 15 — Ticketing ↔ Learning"],
)
def confidence_calibration(
    window_days: Optional[int] = Query(default=30, ge=1, description="Lookback window in days."),
    bucket_size: float = Query(default=0.1, ge=0.05, le=0.5, description="Confidence bucket width (0.05–0.5)."),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> List[ConfidenceCalibrationBucket]:
    from app.services.learning_signals_service import get_calibration_data
    buckets = get_calibration_data(db, window_days=window_days, bucket_size=bucket_size)
    return [ConfidenceCalibrationBucket(**b) for b in buckets]
