"""
Learning Signals Service  –  Phase 15: Ticketing ↔ Continuous Learning
-----------------------------------------------------------------------
Central hub for recording all discrete learning events from the ticketing,
feedback, retrieval, and routing systems.

Design:
  - All writes are append-only (never modify signals)
  - Callers are: feedback_service, ticket_service, domain_router_service
  - Consumers are: metrics_service, confidence_advisor_service
  - Thread-safe: each call commits its own transaction independently

Signal types (see LearningSignalType):
  feedback_up / feedback_down  – user thumbs up/down
  correction                   – user submitted a correction
  ticket_created               – low-confidence ticket auto-generated
  ticket_resolved              – domain expert resolved a ticket
  retrieval_failure            – identified retrieval miss
  hallucination_detected       – LLM fabrication / unverified claim
  routing_error                – domain routing was incorrect
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.learning_signal import LearningSignal, LearningSignalType

logger = logging.getLogger(__name__)


def _new_signal_id() -> str:
    return f"SIG_{uuid.uuid4().hex[:10].upper()}"


# ── Write ─────────────────────────────────────────────────────────────────────

def record_signal(
    db: Session,
    signal_type: str,
    *,
    query_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
    feedback_id: Optional[str] = None,
    domain_id: Optional[Any] = None,
    confidence_score: Optional[float] = None,
    was_correct: Optional[str] = None,     # "yes" | "no" | "partial"
    retrieval_route: Optional[str] = None,
    intent: Optional[str] = None,
    resolution_type: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> LearningSignal:
    """
    Record a single learning signal. Returns the created row.
    Safe to call from within any service — handles its own commit/rollback.

    Args:
        signal_type: One of LearningSignalType constants.
        query_id:    QueryLog.query_id (optional source reference).
        ticket_id:   Ticket.ticket_id (optional source reference).
        feedback_id: Feedback.feedback_id (optional source reference).
        domain_id:   Domain UUID (for routing signals).
        confidence_score: Predicted confidence at query time (for calibration).
        was_correct: Actual correctness ("yes"|"no"|"partial") from user or expert.
        retrieval_route: Which route produced the answer (vector|bm25|graph|hybrid).
        intent:      Query intent classification.
        resolution_type: ResolutionType from ticket resolution.
        details:     Optional JSON payload for extra context.
    """
    if signal_type not in LearningSignalType.ALL:
        logger.warning("[LearningSignals] Unknown signal_type=%r — recording anyway", signal_type)

    row = LearningSignal(
        signal_id=_new_signal_id(),
        signal_type=signal_type,
        query_id=query_id,
        ticket_id=ticket_id,
        feedback_id=feedback_id,
        domain_id=domain_id,
        confidence_score=confidence_score,
        was_correct=was_correct,
        retrieval_route=retrieval_route,
        intent=intent,
        resolution_type=resolution_type,
        details=json.dumps(details) if details else None,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "[LearningSignals] %s | signal=%s query=%s ticket=%s",
            row.signal_id, signal_type, query_id, ticket_id,
        )
        return row
    except Exception as exc:
        db.rollback()
        logger.error("[LearningSignals] Failed to record signal %r: %s", signal_type, exc)
        raise RuntimeError(f"Failed to record learning signal: {exc}") from exc


# ── Read ──────────────────────────────────────────────────────────────────────

def list_signals(
    db: Session,
    *,
    signal_type: Optional[str] = None,
    query_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
    domain_id: Optional[Any] = None,
    window_days: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[LearningSignal]:
    """List learning signals with optional filters."""
    q = db.query(LearningSignal)
    if signal_type:
        q = q.filter(LearningSignal.signal_type == signal_type)
    if query_id:
        q = q.filter(LearningSignal.query_id == query_id)
    if ticket_id:
        q = q.filter(LearningSignal.ticket_id == ticket_id)
    if domain_id:
        q = q.filter(LearningSignal.domain_id == domain_id)
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        q = q.filter(LearningSignal.created_at >= cutoff)
    return (
        q.order_by(LearningSignal.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def count_signals(
    db: Session,
    signal_type: Optional[str] = None,
    window_days: Optional[int] = None,
) -> int:
    """Count signals matching filters."""
    q = db.query(func.count(LearningSignal.id))
    if signal_type:
        q = q.filter(LearningSignal.signal_type == signal_type)
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        q = q.filter(LearningSignal.created_at >= cutoff)
    return q.scalar() or 0


def get_signals_summary(
    db: Session,
    window_days: Optional[int] = None,
) -> Dict[str, int]:
    """
    Count of each signal type within the time window.
    Returns a dict: {signal_type: count}
    """
    q = db.query(LearningSignal.signal_type, func.count(LearningSignal.id))
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        q = q.filter(LearningSignal.created_at >= cutoff)
    rows = q.group_by(LearningSignal.signal_type).all()
    return {sig_type: count for sig_type, count in rows}


def get_calibration_data(
    db: Session,
    window_days: Optional[int] = None,
    bucket_size: float = 0.1,
) -> List[Dict[str, Any]]:
    """
    Confidence calibration analysis: group signals by predicted confidence bucket
    and compute actual correctness rate per bucket.

    Returns a list of bucket dicts:
      {
        "bucket_min": 0.0, "bucket_max": 0.1,
        "total": 12, "correct": 8, "partial": 2, "incorrect": 2,
        "actual_correctness_rate": 0.67,
        "predicted_midpoint": 0.05
      }

    Only includes signals that have both confidence_score AND was_correct set.
    """
    q = db.query(
        LearningSignal.confidence_score,
        LearningSignal.was_correct,
    ).filter(
        LearningSignal.confidence_score.isnot(None),
        LearningSignal.was_correct.isnot(None),
    )
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        q = q.filter(LearningSignal.created_at >= cutoff)

    rows = q.all()
    if not rows:
        return []

    # Build buckets
    buckets: Dict[int, Dict[str, Any]] = {}
    num_buckets = int(1.0 / bucket_size)

    for score, correctness in rows:
        if score is None:
            continue
        # Clamp to [0, 1)
        bucket_idx = min(int(score / bucket_size), num_buckets - 1)
        if bucket_idx not in buckets:
            buckets[bucket_idx] = {
                "bucket_min": round(bucket_idx * bucket_size, 2),
                "bucket_max": round((bucket_idx + 1) * bucket_size, 2),
                "predicted_midpoint": round((bucket_idx + 0.5) * bucket_size, 2),
                "total": 0,
                "correct": 0,
                "partial": 0,
                "incorrect": 0,
            }
        b = buckets[bucket_idx]
        b["total"] += 1
        if correctness == "yes":
            b["correct"] += 1
        elif correctness == "partial":
            b["partial"] += 1
        else:
            b["incorrect"] += 1

    result = []
    for idx in sorted(buckets.keys()):
        b = buckets[idx]
        actual_correct = (b["correct"] + b["partial"] * 0.5) / b["total"] if b["total"] else 0.0
        b["actual_correctness_rate"] = round(actual_correct, 4)
        result.append(b)

    return result
