"""
Routing & Retrieval Improvement  –  Phase 12/15 Module 10
(Steps: Improve Routing, Improve Retrieval, Domain Routing Accuracy)
----------------------------------------------------------------------
Closes the feedback loop: once enough 👍/👎 ratings have accumulated for a
retrieval route, this module lets that history influence FUTURE routing
and retrieval-breadth decisions.

  Improve Routing    – if a route's satisfaction (share of 👍) for a given
                       intent falls below settings.learning_satisfaction_threshold
                       (with at least settings.learning_min_samples ratings),
                       future queries with that intent are escalated to
                       "hybrid" instead — the route that combines all three
                       retrieval strategies rather than betting on one that
                       has been underperforming.
  Improve Retrieval   – independently, an underperforming route's top_k is
                        widened (up to a capped multiplier) so it pulls in
                        more candidate evidence per query, on the theory
                        that a chunk that WOULD have helped was likely being
                        missed by too narrow a retrieval breadth.

Phase 15 adds:
  Domain Routing Accuracy – % of routed tickets NOT flagged as routing_error
  Routing Failure Patterns – which routes/intents have the most failures
  Routing Threshold Suggestion – data-backed threshold recommendations

Both are conservative by design: with too few ratings, no adjustment is
made and Phase 8's deterministic router/breadth is used unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.feedback import Feedback
from app.models.query_log import QueryLog

logger = logging.getLogger(__name__)


@dataclass
class RouteStats:
    route: str
    intent: Optional[str]
    samples: int
    satisfaction: Optional[float]   # None if samples < learning_min_samples


def get_route_satisfaction(db: Session, route: str, intent: Optional[str] = None) -> RouteStats:
    """
    Share of 👍 among rated queries that used *route* (optionally scoped to
    one intent). satisfaction stays None until at least
    settings.learning_min_samples ratings exist, so a couple of early
    downvotes can't swing routing decisions.
    """
    q = (
        db.query(Feedback, QueryLog.intent)
        .join(QueryLog, Feedback.query_id == QueryLog.query_id)
        .filter(QueryLog.route == route)
    )
    if intent:
        q = q.filter(QueryLog.intent == intent)

    rows = q.all()
    samples = len(rows)
    if samples < settings.learning_min_samples:
        return RouteStats(route=route, intent=intent, samples=samples, satisfaction=None)

    up = sum(1 for f, _ in rows if f.rating == "up")
    return RouteStats(route=route, intent=intent, samples=samples, satisfaction=round(up / samples, 4))


def suggest_route_override(
    db: Session, base_route: str, intent: Optional[str]
) -> Optional[str]:
    """
    Step: Improve Routing. Returns "hybrid" if *base_route* is a confirmed
    underperformer for *intent*, else None (keep Phase 8's decision).
    Never overrides a decision that's already "hybrid".
    """
    if not settings.continuous_learning_enabled or base_route == "hybrid":
        return None

    stats = get_route_satisfaction(db, base_route, intent)
    if stats.satisfaction is None or stats.satisfaction >= settings.learning_satisfaction_threshold:
        return None

    logger.info(
        "[RoutingImprovement] 📉 Route '%s' underperforming for intent=%s "
        "(satisfaction=%.2f over %d samples) -> escalating to hybrid",
        base_route, intent, stats.satisfaction, stats.samples,
    )
    return "hybrid"


def suggest_topk_multiplier(db: Session, route: str, intent: Optional[str] = None) -> float:
    """
    Step: Improve Retrieval. Returns a multiplier (>= 1.0) to widen top_k
    for *route* if it's a confirmed underperformer, else 1.0 (no change).
    """
    if not settings.continuous_learning_enabled:
        return 1.0

    stats = get_route_satisfaction(db, route, intent)
    if stats.satisfaction is None or stats.satisfaction >= settings.learning_satisfaction_threshold:
        return 1.0

    logger.info(
        "[RoutingImprovement] 📈 Widening retrieval breadth for underperforming "
        "route '%s' (satisfaction=%.2f, x%.1f)",
        route, stats.satisfaction, settings.learning_topk_boost,
    )
    return settings.learning_topk_boost


# ── Phase 15: Domain Routing Accuracy & Failure Patterns ──────────────────────

@dataclass
class RoutingAccuracyStats:
    """Statistics about domain routing accuracy over a time window."""
    total_routed: int
    routing_errors: int
    accuracy: Optional[float]        # 1 - (errors / routed), None if no data
    error_rate: Optional[float]
    needs_triage_count: int
    window_days: Optional[int]


def get_domain_routing_accuracy(
    db: Session,
    window_days: Optional[int] = 30,
    domain_id: Optional[str] = None,
) -> RoutingAccuracyStats:
    """
    Compute domain routing accuracy: % of routed tickets NOT flagged as
    routing_error in the learning signals.

    Args:
        db: DB session
        window_days: Lookback window (None = all-time)
        domain_id: Filter to a specific domain (None = all domains)
    """
    from app.models.learning_signal import LearningSignal, LearningSignalType
    from app.models.ticket import Ticket

    cutoff = None
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Total routed (not needs_triage)
    routed_q = db.query(func.count(Ticket.id)).filter(
        Ticket.needs_triage.is_(False),
        Ticket.routed_domain_id.isnot(None),
    )
    if cutoff:
        routed_q = routed_q.filter(Ticket.created_at >= cutoff)
    if domain_id:
        try:
            import uuid
            routed_q = routed_q.filter(Ticket.routed_domain_id == uuid.UUID(str(domain_id)))
        except (ValueError, TypeError):
            pass
    total_routed = routed_q.scalar() or 0

    # needs_triage count
    triage_q = db.query(func.count(Ticket.id)).filter(Ticket.needs_triage.is_(True))
    if cutoff:
        triage_q = triage_q.filter(Ticket.created_at >= cutoff)
    needs_triage_count = triage_q.scalar() or 0

    # Routing errors from learning signals
    err_q = db.query(func.count(LearningSignal.id)).filter(
        LearningSignal.signal_type == LearningSignalType.ROUTING_ERROR
    )
    if cutoff:
        err_q = err_q.filter(LearningSignal.created_at >= cutoff)
    if domain_id:
        try:
            import uuid
            err_q = err_q.filter(LearningSignal.domain_id == uuid.UUID(str(domain_id)))
        except (ValueError, TypeError):
            pass
    routing_errors = err_q.scalar() or 0

    if total_routed == 0:
        return RoutingAccuracyStats(
            total_routed=0, routing_errors=routing_errors,
            accuracy=None, error_rate=None,
            needs_triage_count=needs_triage_count, window_days=window_days,
        )

    error_rate = routing_errors / total_routed
    accuracy = max(0.0, 1.0 - error_rate)

    return RoutingAccuracyStats(
        total_routed=total_routed,
        routing_errors=routing_errors,
        accuracy=round(accuracy, 4),
        error_rate=round(error_rate, 4),
        needs_triage_count=needs_triage_count,
        window_days=window_days,
    )


@dataclass
class RetrievalFailurePattern:
    """A retrieval failure pattern: which route/intent fails most often."""
    route: str
    intent: Optional[str]
    failure_count: int
    total_signals: int
    failure_rate: float


def get_retrieval_failure_patterns(
    db: Session,
    window_days: Optional[int] = 30,
    top_n: int = 10,
) -> List[RetrievalFailurePattern]:
    """
    Identify which retrieval routes and intents are failing most often.
    Uses learning_signals of type RETRIEVAL_FAILURE grouped by route and intent.

    Returns top_n patterns sorted by failure_rate descending.
    """
    from app.models.learning_signal import LearningSignal, LearningSignalType

    cutoff = None
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Count retrieval failures by route + intent
    fail_q = (
        db.query(
            LearningSignal.retrieval_route,
            LearningSignal.intent,
            func.count(LearningSignal.id).label("failure_count"),
        )
        .filter(LearningSignal.signal_type == LearningSignalType.RETRIEVAL_FAILURE)
    )
    if cutoff:
        fail_q = fail_q.filter(LearningSignal.created_at >= cutoff)
    fail_rows = (
        fail_q
        .group_by(LearningSignal.retrieval_route, LearningSignal.intent)
        .all()
    )

    if not fail_rows:
        return []

    # Total signals per route/intent (for denominator)
    total_q = (
        db.query(
            LearningSignal.retrieval_route,
            LearningSignal.intent,
            func.count(LearningSignal.id).label("total"),
        )
    )
    if cutoff:
        total_q = total_q.filter(LearningSignal.created_at >= cutoff)
    total_rows = (
        total_q
        .group_by(LearningSignal.retrieval_route, LearningSignal.intent)
        .all()
    )
    totals: Dict[tuple, int] = {(r, i): t for r, i, t in total_rows}

    patterns = []
    for route, intent, failure_count in fail_rows:
        total = totals.get((route, intent), failure_count)
        failure_rate = round(failure_count / total, 4) if total > 0 else 0.0
        patterns.append(RetrievalFailurePattern(
            route=route or "unknown",
            intent=intent,
            failure_count=failure_count,
            total_signals=total,
            failure_rate=failure_rate,
        ))

    patterns.sort(key=lambda p: p.failure_rate, reverse=True)
    return patterns[:top_n]


def get_improvement_summary(
    db: Session,
    window_days: Optional[int] = 30,
) -> Dict:
    """
    Consolidated improvement summary for the admin dashboard.
    Combines routing accuracy, retrieval failure patterns, and route satisfaction.
    """
    routing_stats = get_domain_routing_accuracy(db, window_days=window_days)
    failure_patterns = get_retrieval_failure_patterns(db, window_days=window_days)

    # Per-route satisfaction
    routes = ["vector", "bm25", "graph", "hybrid"]
    route_satisfaction = {}
    for r in routes:
        stats = get_route_satisfaction(db, r)
        route_satisfaction[r] = {
            "samples": stats.samples,
            "satisfaction": stats.satisfaction,
            "min_samples_reached": stats.samples >= settings.learning_min_samples,
        }

    return {
        "window_days": window_days,
        "domain_routing": {
            "total_routed": routing_stats.total_routed,
            "routing_errors": routing_stats.routing_errors,
            "accuracy": routing_stats.accuracy,
            "error_rate": routing_stats.error_rate,
            "needs_triage_count": routing_stats.needs_triage_count,
        },
        "retrieval_failure_patterns": [
            {
                "route": p.route,
                "intent": p.intent,
                "failure_count": p.failure_count,
                "total_signals": p.total_signals,
                "failure_rate": p.failure_rate,
            }
            for p in failure_patterns
        ],
        "route_satisfaction": route_satisfaction,
        "learning_settings": {
            "continuous_learning_enabled": settings.continuous_learning_enabled,
            "min_samples": settings.learning_min_samples,
            "satisfaction_threshold": settings.learning_satisfaction_threshold,
            "topk_boost": settings.learning_topk_boost,
            "topk_boost_max": settings.learning_topk_boost_max,
        },
    }
