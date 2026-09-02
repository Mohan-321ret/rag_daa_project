"""
Confidence Threshold Advisor  –  Phase 15: Controlled Learning Pipeline
-----------------------------------------------------------------------
Analyzes accumulated learning signals to suggest improved threshold values
for:
  - ticket_confidence_threshold:  When to auto-generate a ticket (RAG quality gate)
  - routing_confidence_threshold: When to flag a routing decision as uncertain

Design principles:
  1. READ-ONLY analysis: this service NEVER modifies any setting automatically.
  2. All suggestions are written to `threshold_history` with source="auto_suggestion".
  3. An admin must explicitly call the threshold-apply API to enact any change.
  4. Justification is always data-backed and stored with the suggestion.
  5. Minimum sample guards (configured in settings) prevent noisy early signals
     from driving changes.

Methodology:
  - Confidence calibration: compare predicted confidence buckets vs actual
    correctness rate (from feedback signals)
  - Routing error analysis: compute routing error rate and suggest raising
    routing threshold if errors are above acceptable level
  - Ticket generation rate: if too many tickets, threshold may be too low;
    if resolution shows most were "knowledge_missing", threshold is appropriate
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.learning_signal import LearningSignalType
from app.models.threshold_history import ThresholdHistory, ThresholdSource, TRACKABLE_METRICS
from app.services.learning_signals_service import (
    get_calibration_data,
    get_signals_summary,
)

logger = logging.getLogger(__name__)

# Acceptable routing error rate — above this, suggest raising routing threshold
ROUTING_ERROR_RATE_ACCEPTABLE = 0.15

# Minimum samples before making any suggestion
MIN_CALIBRATION_SAMPLES = 20

# Maximum suggested change per recommendation (±)
MAX_THRESHOLD_DELTA = 0.15


def _new_history_id() -> str:
    return f"THR_{uuid.uuid4().hex[:10].upper()}"


# ── Threshold Suggestions ─────────────────────────────────────────────────────

def _get_current_threshold(metric_name: str) -> float:
    """Get the current threshold value from settings."""
    return getattr(settings, metric_name, 0.5)


def analyze_confidence_threshold(
    db: Session,
    window_days: Optional[int] = 30,
) -> Optional[Dict[str, Any]]:
    """
    Analyze confidence calibration data and suggest a new ticket_confidence_threshold.

    Returns a suggestion dict or None if insufficient data.

    Logic:
      - Build calibration buckets from feedback signals (confidence vs correctness)
      - Find the confidence level at which actual correctness crosses 0.7
        (i.e. we're confident enough 70% of the time at this score)
      - If that crossover point differs from current threshold by > 0.05,
        suggest the new value
    """
    calibration = get_calibration_data(db, window_days=window_days)
    total_samples = sum(b["total"] for b in calibration)

    if total_samples < MIN_CALIBRATION_SAMPLES:
        logger.info(
            "[ConfidenceAdvisor] Insufficient calibration samples (%d < %d)",
            total_samples, MIN_CALIBRATION_SAMPLES,
        )
        return None

    # Find where correctness first crosses 0.70 threshold from left
    crossover_bucket = None
    for bucket in sorted(calibration, key=lambda b: b["bucket_min"]):
        if bucket["actual_correctness_rate"] >= 0.70 and bucket["total"] >= 3:
            crossover_bucket = bucket
            break

    if crossover_bucket is None:
        # No bucket has ≥70% correctness → suggest slightly higher threshold
        current = _get_current_threshold("ticket_confidence_threshold")
        suggested = min(current + 0.05, 0.95)
        reason = (
            f"No confidence bucket shows ≥70% actual correctness in the last "
            f"{window_days} days ({total_samples} samples). "
            f"Suggest raising ticket threshold slightly to capture more questionable answers."
        )
    else:
        suggested = round(crossover_bucket["bucket_min"], 2)
        current = _get_current_threshold("ticket_confidence_threshold")
        if abs(suggested - current) < 0.03:
            return None  # No meaningful change needed
        reason = (
            f"Calibration analysis over {window_days} days ({total_samples} samples): "
            f"confidence bucket {crossover_bucket['bucket_min']:.1f}–"
            f"{crossover_bucket['bucket_max']:.1f} achieves "
            f"{crossover_bucket['actual_correctness_rate']*100:.1f}% actual correctness. "
            f"Adjusting ticket threshold to {suggested} would better match actual performance."
        )

    # Clamp change magnitude
    current = _get_current_threshold("ticket_confidence_threshold")
    suggested = max(current - MAX_THRESHOLD_DELTA, min(current + MAX_THRESHOLD_DELTA, suggested))
    suggested = round(max(0.1, min(0.95, suggested)), 2)

    return {
        "metric_name": "ticket_confidence_threshold",
        "current_value": current,
        "suggested_value": suggested,
        "reason": reason,
        "supporting_data": calibration,
        "total_samples": total_samples,
    }


def analyze_routing_threshold(
    db: Session,
    window_days: Optional[int] = 30,
) -> Optional[Dict[str, Any]]:
    """
    Analyze routing error signals and suggest a new routing_confidence_threshold.

    Logic:
      - Count routing_error signals vs total ticket_created signals
      - If error rate > ROUTING_ERROR_RATE_ACCEPTABLE, suggest raising threshold
      - If error rate < 0.05 and current threshold is high, suggest lowering slightly
    """
    summary = get_signals_summary(db, window_days=window_days)
    routing_errors = summary.get(LearningSignalType.ROUTING_ERROR, 0)
    tickets_created = summary.get(LearningSignalType.TICKET_CREATED, 0)

    if tickets_created < 10:
        logger.info(
            "[ConfidenceAdvisor] Insufficient ticket signals (%d) for routing analysis",
            tickets_created,
        )
        return None

    error_rate = routing_errors / tickets_created if tickets_created > 0 else 0.0
    current = _get_current_threshold("routing_confidence_threshold")

    if error_rate > ROUTING_ERROR_RATE_ACCEPTABLE:
        # Too many routing errors — raise the threshold to be more conservative
        suggested = round(min(current + 0.10, 0.90), 2)
        reason = (
            f"Routing error rate is {error_rate*100:.1f}% ({routing_errors}/{tickets_created} tickets) "
            f"over the last {window_days} days, exceeding acceptable rate of "
            f"{ROUTING_ERROR_RATE_ACCEPTABLE*100:.0f}%. "
            f"Raising routing_confidence_threshold from {current} to {suggested} "
            f"will send more uncertain tickets to triage rather than auto-routing incorrectly."
        )
    elif error_rate < 0.05 and current > 0.45:
        # Very few routing errors — can be slightly less conservative
        suggested = round(max(current - 0.05, 0.30), 2)
        reason = (
            f"Routing error rate is low ({error_rate*100:.1f}%, {routing_errors}/{tickets_created}) "
            f"over the last {window_days} days. "
            f"The classifier is performing well; threshold can be lowered slightly "
            f"from {current} to {suggested} to reduce unnecessary triage."
        )
    else:
        return None  # Current threshold is performing well

    if abs(suggested - current) < 0.02:
        return None

    return {
        "metric_name": "routing_confidence_threshold",
        "current_value": current,
        "suggested_value": suggested,
        "reason": reason,
        "supporting_data": {
            "routing_error_rate": round(error_rate, 4),
            "routing_errors": routing_errors,
            "tickets_created": tickets_created,
        },
        "total_samples": tickets_created,
    }


def generate_suggestions(
    db: Session,
    window_days: Optional[int] = 30,
    persist: bool = True,
) -> List[ThresholdHistory]:
    """
    Run all threshold analyses and save suggestions to threshold_history.

    Args:
        db: DB session
        window_days: Analysis window
        persist: If True, write suggestions to DB (default). False = dry-run.

    Returns:
        List of ThresholdHistory rows created (may be empty if no changes needed).
    """
    created: List[ThresholdHistory] = []

    analyses = [
        analyze_confidence_threshold(db, window_days=window_days),
        analyze_routing_threshold(db, window_days=window_days),
    ]

    for analysis in analyses:
        if analysis is None:
            continue

        row = ThresholdHistory(
            history_id=_new_history_id(),
            metric_name=analysis["metric_name"],
            old_value=analysis["current_value"],
            new_value=analysis["suggested_value"],
            reason=analysis["reason"],
            supporting_data=json.dumps(analysis["supporting_data"]),
            source=ThresholdSource.AUTO_SUGGESTION,
            approved_by=None,
            applied_at=None,
        )

        if persist:
            try:
                db.add(row)
                db.commit()
                db.refresh(row)
                logger.info(
                    "[ConfidenceAdvisor] 💡 Suggestion %s: %s %.3f → %.3f",
                    row.history_id, row.metric_name, row.old_value, row.new_value,
                )
            except Exception as exc:
                db.rollback()
                logger.error("[ConfidenceAdvisor] Failed to persist suggestion: %s", exc)
                continue

        created.append(row)

    return created


# ── Apply (Admin Action) ───────────────────────────────────────────────────────

def apply_threshold(
    db: Session,
    suggestion_id: str,
    approved_by_user_id: Any,
) -> ThresholdHistory:
    """
    Admin applies a pending threshold suggestion.

    Creates a new threshold_history row with source="admin_applied" and
    updates the relevant SystemSetting in the database.

    This is the ONLY function that modifies operational thresholds.
    """
    # Find the suggestion
    suggestion = (
        db.query(ThresholdHistory)
        .filter(
            ThresholdHistory.history_id == suggestion_id,
            ThresholdHistory.source == ThresholdSource.AUTO_SUGGESTION,
        )
        .first()
    )
    if suggestion is None:
        raise ValueError(f"No pending suggestion found with id={suggestion_id!r}")

    if suggestion.applied_at is not None:
        raise ValueError(
            f"Suggestion {suggestion_id!r} was already applied at {suggestion.applied_at}"
        )

    # Persist the admin action record
    now = datetime.now(timezone.utc)
    applied_row = ThresholdHistory(
        history_id=_new_history_id(),
        metric_name=suggestion.metric_name,
        old_value=suggestion.old_value,
        new_value=suggestion.new_value,
        reason=f"Admin applied suggestion {suggestion_id}: {suggestion.reason}",
        supporting_data=suggestion.supporting_data,
        source=ThresholdSource.ADMIN_APPLIED,
        approved_by=approved_by_user_id,
        applied_at=now,
        suggestion_id=suggestion_id,
    )

    # Mark the suggestion as applied
    suggestion.applied_at = now
    suggestion.approved_by = approved_by_user_id

    # Update the SystemSetting in the database
    from app.models.system_setting import SystemSetting
    setting = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == suggestion.metric_name)
        .first()
    )
    if setting:
        setting.value = str(suggestion.new_value)
        setting.updated_at = now
    else:
        db.add(SystemSetting(
            key=suggestion.metric_name,
            value=str(suggestion.new_value),
        ))

    try:
        db.add(applied_row)
        db.commit()
        db.refresh(applied_row)
        logger.info(
            "[ConfidenceAdvisor] ✅ Admin %s applied threshold %s: %.3f → %.3f",
            approved_by_user_id, suggestion.metric_name,
            suggestion.old_value, suggestion.new_value,
        )
        return applied_row
    except Exception as exc:
        db.rollback()
        logger.error("[ConfidenceAdvisor] Failed to apply threshold: %s", exc)
        raise RuntimeError(f"Failed to apply threshold: {exc}") from exc


# ── History Queries ───────────────────────────────────────────────────────────

def list_threshold_history(
    db: Session,
    metric_name: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ThresholdHistory]:
    """List threshold history entries with optional filters."""
    q = db.query(ThresholdHistory)
    if metric_name:
        q = q.filter(ThresholdHistory.metric_name == metric_name)
    if source:
        q = q.filter(ThresholdHistory.source == source)
    return (
        q.order_by(ThresholdHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_pending_suggestions(
    db: Session,
    metric_name: Optional[str] = None,
) -> List[ThresholdHistory]:
    """Return auto_suggestions that have not yet been applied."""
    q = db.query(ThresholdHistory).filter(
        ThresholdHistory.source == ThresholdSource.AUTO_SUGGESTION,
        ThresholdHistory.applied_at.is_(None),
    )
    if metric_name:
        q = q.filter(ThresholdHistory.metric_name == metric_name)
    return q.order_by(ThresholdHistory.created_at.desc()).all()
