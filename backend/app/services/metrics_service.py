"""
Performance Metrics  –  Phase 15 Module 10 (Extended Metrics)
------------------------------------------------------------------------
Aggregates QueryLog telemetry + Feedback ratings + Learning Signals into
eight tracked metrics:

Phase 12 (original 4):
  Retrieval Accuracy  – share of 👍 among rated queries, broken down by
                        retrieval route (vector/bm25/graph/hybrid).
  Latency              – average / p95 end-to-end response time (ms).
  Hallucination Rate    – share of queries where Phase 11's Evidence
                         Verification flagged >=1 hallucinated claim.
  User Satisfaction    – overall share of 👍 among ALL rated queries.

Phase 15 (4 new):
  Ticket Generation Rate     – tickets_created / total_queries.
  Ticket Resolution Rate     – resolved_tickets / total_tickets (window).
  Domain Routing Accuracy    – % of routed tickets NOT flagged as routing_error.
  Avg Ticket Resolution Time – mean hours from ticket creation → resolution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.feedback import Feedback
from app.models.query_log import QueryLog
from app.models.ticket import Ticket, TicketStatus

logger = logging.getLogger(__name__)


@dataclass
class MetricsSummary:
    # ── Phase 12 metrics ──────────────────────────────────────────────────────
    window_days: Optional[int]
    total_queries: int
    total_rated: int
    user_satisfaction: Optional[float]            # None if no feedback yet
    hallucination_rate: Optional[float]
    avg_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    queries_by_route: Dict[str, int] = field(default_factory=dict)
    retrieval_accuracy_by_route: Dict[str, Optional[float]] = field(default_factory=dict)
    samples_by_route: Dict[str, int] = field(default_factory=dict)

    # ── Phase 15 extended metrics ─────────────────────────────────────────────
    ticket_generation_rate: Optional[float] = None   # tickets / total_queries
    ticket_resolution_rate: Optional[float] = None   # resolved / total_tickets
    domain_routing_accuracy: Optional[float] = None  # 1 - (routing_errors / routed_tickets)
    avg_ticket_resolution_time_hours: Optional[float] = None
    total_tickets: int = 0
    resolved_tickets: int = 0
    signal_counts: Dict[str, int] = field(default_factory=dict)


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def compute_metrics(
    db: Session,
    window_days: Optional[int] = None,
    route: Optional[str] = None,
) -> MetricsSummary:
    """Aggregate QueryLog + Feedback + Ticket + LearningSignal rows into 8 metrics."""
    cutoff: Optional[datetime] = None
    if window_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # ── Phase 12: QueryLog aggregation ────────────────────────────────────────
    query = db.query(QueryLog)
    if cutoff:
        query = query.filter(QueryLog.created_at >= cutoff)
    if route:
        query = query.filter(QueryLog.route == route)

    logs: List[QueryLog] = query.all()
    total_queries = len(logs)

    latencies = [l.latency_ms for l in logs if l.latency_ms is not None]
    hallucinated = sum(1 for l in logs if l.was_rewritten or l.hallucinations_detected > 0)

    queries_by_route: Dict[str, int] = {}
    route_by_query: Dict[str, Optional[str]] = {}
    for l in logs:
        route_by_query[l.query_id] = l.route
        if l.route:
            queries_by_route[l.route] = queries_by_route.get(l.route, 0) + 1

    query_ids = list(route_by_query.keys())
    feedback_rows: List[Feedback] = (
        db.query(Feedback).filter(Feedback.query_id.in_(query_ids)).all()
        if query_ids else []
    )

    total_rated = len(feedback_rows)
    up = sum(1 for f in feedback_rows if f.rating == "up")
    user_satisfaction = round(up / total_rated, 4) if total_rated else None

    route_up: Dict[str, int] = {}
    route_total: Dict[str, int] = {}
    for f in feedback_rows:
        r = route_by_query.get(f.query_id)
        if not r:
            continue
        route_total[r] = route_total.get(r, 0) + 1
        if f.rating == "up":
            route_up[r] = route_up.get(r, 0) + 1

    retrieval_accuracy_by_route: Dict[str, Optional[float]] = {
        r: round(route_up.get(r, 0) / total, 4) if total else None
        for r, total in route_total.items()
    }

    # ── Phase 15: Ticket metrics ───────────────────────────────────────────────
    ticket_q = db.query(Ticket)
    if cutoff:
        ticket_q = ticket_q.filter(Ticket.created_at >= cutoff)

    total_tickets = ticket_q.count()
    resolved_tickets = ticket_q.filter(
        Ticket.status.in_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value])
    ).count()

    ticket_generation_rate = (
        round(total_tickets / total_queries, 4) if total_queries > 0 else None
    )
    ticket_resolution_rate = (
        round(resolved_tickets / total_tickets, 4) if total_tickets > 0 else None
    )

    # Average ticket resolution time
    resolved_rows = (
        db.query(Ticket.created_at, Ticket.resolved_at)
        .filter(
            Ticket.resolved_at.isnot(None),
            Ticket.created_at.isnot(None),
            Ticket.status.in_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]),
        )
    )
    if cutoff:
        resolved_rows = resolved_rows.filter(Ticket.created_at >= cutoff)
    resolved_rows = resolved_rows.all()

    avg_ticket_resolution_time_hours = None
    if resolved_rows:
        valid_durations = []
        for c_at, r_at in resolved_rows:
            if c_at and r_at:
                # Ensure timezone-aware comparison
                if hasattr(c_at, 'tzinfo') and c_at.tzinfo is None:
                    c_at = c_at.replace(tzinfo=timezone.utc)
                if hasattr(r_at, 'tzinfo') and r_at.tzinfo is None:
                    r_at = r_at.replace(tzinfo=timezone.utc)
                if r_at >= c_at:
                    valid_durations.append((r_at - c_at).total_seconds() / 3600.0)
        if valid_durations:
            avg_ticket_resolution_time_hours = round(
                sum(valid_durations) / len(valid_durations), 2
            )

    # ── Phase 15: Domain Routing Accuracy ─────────────────────────────────────
    domain_routing_accuracy = _compute_routing_accuracy(db, cutoff)

    # ── Phase 15: Signal Counts ────────────────────────────────────────────────
    signal_counts = _get_signal_counts(db, cutoff)

    summary = MetricsSummary(
        window_days=window_days,
        total_queries=total_queries,
        total_rated=total_rated,
        user_satisfaction=user_satisfaction,
        hallucination_rate=round(hallucinated / total_queries, 4) if total_queries else None,
        avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else None,
        p95_latency_ms=round(_percentile(latencies, 0.95), 2) if latencies else None,
        queries_by_route=queries_by_route,
        retrieval_accuracy_by_route=retrieval_accuracy_by_route,
        samples_by_route=route_total,
        # Phase 15 extended
        ticket_generation_rate=ticket_generation_rate,
        ticket_resolution_rate=ticket_resolution_rate,
        domain_routing_accuracy=domain_routing_accuracy,
        avg_ticket_resolution_time_hours=avg_ticket_resolution_time_hours,
        total_tickets=total_tickets,
        resolved_tickets=resolved_tickets,
        signal_counts=signal_counts,
    )
    logger.info(
        "[Metrics] queries=%d rated=%d satisfaction=%s hallucination_rate=%s "
        "ticket_gen_rate=%s ticket_res_rate=%s routing_accuracy=%s",
        total_queries, total_rated, user_satisfaction,
        summary.hallucination_rate, ticket_generation_rate,
        ticket_resolution_rate, domain_routing_accuracy,
    )
    return summary


def _compute_routing_accuracy(
    db: Session,
    cutoff: Optional[datetime],
) -> Optional[float]:
    """
    Domain routing accuracy = 1 - (routing_error signals / routed tickets).
    Returns None if insufficient data.
    """
    try:
        from app.models.learning_signal import LearningSignal, LearningSignalType

        # Total routed tickets (not needs_triage)
        routed_q = db.query(func.count(Ticket.id)).filter(
            Ticket.needs_triage.is_(False),
            Ticket.routed_domain_id.isnot(None),
        )
        if cutoff:
            routed_q = routed_q.filter(Ticket.created_at >= cutoff)
        total_routed = routed_q.scalar() or 0

        if total_routed == 0:
            return None

        # Routing error signals
        err_q = db.query(func.count(LearningSignal.id)).filter(
            LearningSignal.signal_type == LearningSignalType.ROUTING_ERROR
        )
        if cutoff:
            err_q = err_q.filter(LearningSignal.created_at >= cutoff)
        routing_errors = err_q.scalar() or 0

        error_rate = routing_errors / total_routed
        return round(max(0.0, 1.0 - error_rate), 4)
    except Exception as exc:
        logger.warning("[Metrics] routing accuracy computation failed: %s", exc)
        return None


def _get_signal_counts(
    db: Session,
    cutoff: Optional[datetime],
) -> Dict[str, int]:
    """Count of each learning signal type within the window."""
    try:
        from app.models.learning_signal import LearningSignal
        q = db.query(LearningSignal.signal_type, func.count(LearningSignal.id))
        if cutoff:
            q = q.filter(LearningSignal.created_at >= cutoff)
        return {sig_type: cnt for sig_type, cnt in q.group_by(LearningSignal.signal_type).all()}
    except Exception as exc:
        logger.warning("[Metrics] signal count aggregation failed: %s", exc)
        return {}
