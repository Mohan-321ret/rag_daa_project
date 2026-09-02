"""
Learning Pipeline API Router  –  Phase 15: Ticketing ↔ Continuous Learning
---------------------------------------------------------------------------
Controlled, auditable learning pipeline management endpoints:

  GET  /api/v1/learning/signals                – Paginated learning signal log
  GET  /api/v1/learning/threshold-history      – Full audit trail of threshold changes
  GET  /api/v1/learning/threshold-suggestions  – Pending auto-suggestions (not yet applied)
  POST /api/v1/learning/threshold-suggestions/generate – Trigger fresh analysis + suggestions
  POST /api/v1/learning/threshold-apply        – Admin applies a suggestion (writes to DB)
  GET  /api/v1/learning/improvement-report     – Routing + retrieval improvement summary

Design:
  - All reads are open to platform analytics viewers
  - threshold-apply is restricted to admins (SYSTEM_SETTINGS_MANAGE permission)
  - No endpoint modifies retrieval index, model weights, or routing directly
  - Every applied change is logged to threshold_history with approved_by user
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.schemas.learning import (
    ImprovementReportResponse,
    LearningSignalOut,
    PendingSuggestionOut,
    SignalListResponse,
    ThresholdApplyRequest,
    ThresholdApplyResponse,
    ThresholdHistoryOut,
)
from app.services.auth_service import get_current_user, require_permission
from app.services.confidence_advisor_service import (
    apply_threshold,
    generate_suggestions,
    get_pending_suggestions,
    list_threshold_history,
)
from app.services.learning_signals_service import (
    count_signals,
    get_signals_summary,
    list_signals,
)
from app.services.routing_improvement_service import get_improvement_summary
from app.core.permissions import Permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/learning",
    tags=["Phase 15 — Ticketing ↔ Continuous Learning"],
)

# Permission alias: threshold apply requires platform admin level
_THRESHOLD_APPLY_PERMISSION = Permission.SYSTEM_CONFIG


# ── Learning Signal Log ───────────────────────────────────────────────────────

@router.get(
    "/signals",
    response_model=SignalListResponse,
    summary="Browse the learning signal log",
    description=(
        "Paginated list of all learning signals — the raw events driving the "
        "continuous learning pipeline. Signals are emitted by: feedback submission, "
        "ticket creation, ticket resolution, domain routing errors.\n\n"
        "Signal types: `feedback_up`, `feedback_down`, `correction`, `ticket_created`, "
        "`ticket_resolved`, `retrieval_failure`, `hallucination_detected`, `routing_error`"
    ),
)
def list_signal_log(
    signal_type: Optional[str] = Query(default=None, description="Filter by signal type"),
    query_id: Optional[str] = Query(default=None, description="Filter by query_id"),
    ticket_id: Optional[str] = Query(default=None, description="Filter by ticket_id"),
    window_days: Optional[int] = Query(default=30, ge=1, description="Lookback window in days"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> SignalListResponse:
    signals = list_signals(
        db,
        signal_type=signal_type,
        query_id=query_id,
        ticket_id=ticket_id,
        window_days=window_days,
        limit=limit,
        offset=offset,
    )
    total = count_signals(db, signal_type=signal_type, window_days=window_days)
    counts = get_signals_summary(db, window_days=window_days)

    return SignalListResponse(
        total=total,
        offset=offset,
        limit=limit,
        signals=[LearningSignalOut.model_validate(s) for s in signals],
        signal_counts=counts,
    )


# ── Threshold History ─────────────────────────────────────────────────────────

@router.get(
    "/threshold-history",
    response_model=List[ThresholdHistoryOut],
    summary="Auditable log of all threshold changes and suggestions",
    description=(
        "Complete audit trail: every threshold suggestion (source=`auto_suggestion`) "
        "and every admin-applied change (source=`admin_applied`). "
        "Filter by `metric_name` or `source` to narrow results."
    ),
)
def threshold_history(
    metric_name: Optional[str] = Query(
        default=None,
        description="e.g. 'ticket_confidence_threshold' or 'routing_confidence_threshold'",
    ),
    source: Optional[str] = Query(
        default=None,
        description="'auto_suggestion' or 'admin_applied'",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> List[ThresholdHistoryOut]:
    rows = list_threshold_history(
        db, metric_name=metric_name, source=source, limit=limit, offset=offset
    )
    return [ThresholdHistoryOut.model_validate(r) for r in rows]


# ── Threshold Suggestions ─────────────────────────────────────────────────────

@router.get(
    "/threshold-suggestions",
    response_model=List[PendingSuggestionOut],
    summary="Pending threshold suggestions awaiting admin review",
    description=(
        "Returns auto-generated threshold suggestions that have NOT yet been "
        "applied by an admin. Each suggestion includes the reason and supporting "
        "data (calibration analysis) that drove the recommendation.\n\n"
        "**These are read-only suggestions — they do not change anything until "
        "an admin explicitly calls POST /learning/threshold-apply.**"
    ),
)
def pending_suggestions(
    metric_name: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> List[PendingSuggestionOut]:
    rows = get_pending_suggestions(db, metric_name=metric_name)
    result = []
    for r in rows:
        result.append(PendingSuggestionOut(
            history_id=r.history_id,
            metric_name=r.metric_name,
            current_value=r.old_value or 0.0,
            suggested_value=r.new_value,
            reason=r.reason,
            supporting_data=r.supporting_data,
            created_at=r.created_at,
        ))
    return result


@router.post(
    "/threshold-suggestions/generate",
    response_model=List[ThresholdHistoryOut],
    status_code=status.HTTP_201_CREATED,
    summary="Trigger a fresh analysis and generate threshold suggestions",
    description=(
        "Runs the confidence advisor analysis now and writes any new "
        "suggestions to threshold_history. Returns the created suggestion rows.\n\n"
        "Suggestions are only created when sufficient signal data exists "
        "(minimum sample guards apply). If no changes are warranted, returns "
        "an empty list."
    ),
)
def generate_threshold_suggestions(
    window_days: Optional[int] = Query(default=30, ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> List[ThresholdHistoryOut]:
    rows = generate_suggestions(db, window_days=window_days, persist=True)
    return [ThresholdHistoryOut.model_validate(r) for r in rows]


# ── Threshold Apply (Admin Action) ────────────────────────────────────────────

@router.post(
    "/threshold-apply",
    response_model=ThresholdApplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin: apply a pending threshold suggestion",
    description=(
        "**Admin-only action.** Applies a pending auto-suggestion to the live "
        "system setting and records the action in `threshold_history` with the "
        "approving admin's user ID.\n\n"
        "This is the **ONLY** endpoint that modifies operational thresholds. "
        "It requires `SYSTEM_CONFIG` permission (SUPER_ADMIN / PLATFORM_OWNER). "
        "The change is immediately active for new tickets/queries. "
        "The complete audit trail is available via GET /learning/threshold-history."
    ),
)
def apply_threshold_suggestion(
    body: ThresholdApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
) -> ThresholdApplyResponse:
    try:
        applied = apply_threshold(db, body.suggestion_id, approved_by_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    return ThresholdApplyResponse(
        applied_history_id=applied.history_id,
        metric_name=applied.metric_name,
        old_value=applied.old_value,
        new_value=applied.new_value,
        applied_by=str(current_user.id),
        message=(
            f"Threshold '{applied.metric_name}' updated from "
            f"{applied.old_value} → {applied.new_value}. "
            f"Change logged to threshold_history as {applied.history_id}."
        ),
    )


# ── Improvement Report ────────────────────────────────────────────────────────

@router.get(
    "/improvement-report",
    response_model=ImprovementReportResponse,
    summary="Routing and retrieval improvement summary",
    description=(
        "Consolidated view of:\n"
        "- Domain routing accuracy (% correctly routed tickets)\n"
        "- Retrieval failure patterns (which routes/intents fail most)\n"
        "- Per-route satisfaction (👍 rate, used by Improve Routing logic)\n"
        "- Current learning pipeline settings\n\n"
        "This report informs whether routing escalation and top-k widening "
        "are actively helping, and where further improvements can be made."
    ),
    tags=["Phase 15 — Ticketing ↔ Continuous Learning"],
)
def improvement_report(
    window_days: Optional[int] = Query(default=30, ge=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ANALYTICS_VIEW_PLATFORM)),
) -> ImprovementReportResponse:
    report = get_improvement_summary(db, window_days=window_days)

    domain_data = report["domain_routing"]
    return ImprovementReportResponse(
        window_days=report["window_days"],
        domain_routing={
            "total_routed": domain_data["total_routed"],
            "routing_errors": domain_data["routing_errors"],
            "accuracy": domain_data["accuracy"],
            "error_rate": domain_data["error_rate"],
            "needs_triage_count": domain_data["needs_triage_count"],
        },
        retrieval_failure_patterns=[
            {
                "route": p["route"],
                "intent": p["intent"],
                "failure_count": p["failure_count"],
                "total_signals": p["total_signals"],
                "failure_rate": p["failure_rate"],
            }
            for p in report["retrieval_failure_patterns"]
        ],
        route_satisfaction=report["route_satisfaction"],
        learning_settings=report["learning_settings"],
    )
