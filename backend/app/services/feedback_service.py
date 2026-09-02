"""
Feedback Service  –  Phase 12/15 Module 10 (Steps: Collect, Store, Signal)
---------------------------------------------------------------------------
Collects 👍/👎 reactions and optional free-text corrections against a
specific answer (identified by the query_id QueryLog assigned it) and
stores them for Performance Metrics / Improve Routing / Improve Retrieval
to consume downstream.

Phase 15 adds:
  - Learning signal emission after each feedback submission
  - Support for domain_routing_correct and retrieval_failure_flagged fields
  - Links feedback to the associated ticket (if any)
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.feedback import Feedback
from app.models.query_log import QueryLog
from app.services.query_log_service import get_query_log

logger = logging.getLogger(__name__)

VALID_RATINGS = ("up", "down")


def new_feedback_id() -> str:
    return f"FB_{uuid.uuid4().hex[:10].upper()}"


def submit_feedback(
    db: Session,
    query_id: str,
    rating: str,
    correction_text: Optional[str] = None,
    ticket_id: Optional[str] = None,
    domain_routing_correct: Optional[bool] = None,
    retrieval_failure_flagged: Optional[bool] = None,
) -> Feedback:
    """
    Record a 👍/👎 (and optional correction) against a previously logged query.

    Phase 15: Also emits learning signals for each piece of feedback:
      - feedback_up or feedback_down
      - correction (if correction_text provided)
      - retrieval_failure (if retrieval_failure_flagged=True)
      - routing_error (if domain_routing_correct=False)

    Raises:
        ValueError: If query_id doesn't reference a known QueryLog row, or
                    rating isn't "up"/"down".
    """
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {VALID_RATINGS}, got {rating!r}")

    qlog: Optional[QueryLog] = get_query_log(db, query_id)
    if qlog is None:
        raise ValueError(f"Unknown query_id '{query_id}' — no matching query log found.")

    row = Feedback(
        feedback_id=new_feedback_id(),
        query_id=query_id,
        rating=rating,
        correction_text=correction_text,
        ticket_id=ticket_id,
        domain_routing_correct=domain_routing_correct,
        retrieval_failure_flagged=retrieval_failure_flagged,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "[Feedback] %s %s | query=%s%s",
            "👍" if rating == "up" else "👎", row.feedback_id, query_id,
            " (+correction)" if correction_text else "",
        )
    except Exception as exc:
        db.rollback()
        logger.error("[Feedback] Failed to store feedback for %s: %s", query_id, exc)
        raise RuntimeError(f"Database error while storing feedback: {exc}") from exc

    # ── Phase 15: Emit learning signals ───────────────────────────────────────
    _emit_feedback_signals(
        db=db,
        row=row,
        qlog=qlog,
        correction_text=correction_text,
        domain_routing_correct=domain_routing_correct,
        retrieval_failure_flagged=retrieval_failure_flagged,
    )

    return row


def _emit_feedback_signals(
    db: Session,
    row: Feedback,
    qlog: QueryLog,
    correction_text: Optional[str],
    domain_routing_correct: Optional[bool],
    retrieval_failure_flagged: Optional[bool],
) -> None:
    """
    Emit all relevant learning signals for a feedback submission.
    Failures are logged but do NOT raise — feedback already committed.
    """
    try:
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        common = dict(
            query_id=row.query_id,
            feedback_id=row.feedback_id,
            ticket_id=row.ticket_id,
            confidence_score=qlog.confidence_score if qlog else None,
            retrieval_route=qlog.route if qlog else None,
            intent=qlog.intent if qlog else None,
        )

        # Primary signal: 👍 or 👎
        signal_type = (
            LearningSignalType.FEEDBACK_UP if row.rating == "up"
            else LearningSignalType.FEEDBACK_DOWN
        )
        was_correct = "yes" if row.rating == "up" else "no"
        record_signal(db, signal_type, was_correct=was_correct, **common)

        # Correction signal
        if correction_text:
            record_signal(
                db,
                LearningSignalType.CORRECTION,
                was_correct="no",
                details={"correction_preview": correction_text[:200]},
                **common,
            )

        # Retrieval failure signal
        if retrieval_failure_flagged:
            record_signal(
                db,
                LearningSignalType.RETRIEVAL_FAILURE,
                was_correct="no",
                details={"source": "user_flagged"},
                **common,
            )

        # Routing error signal
        if domain_routing_correct is False:
            record_signal(
                db,
                LearningSignalType.ROUTING_ERROR,
                details={"source": "user_flagged", "domain_routing_correct": False},
                **common,
            )

    except Exception as exc:
        logger.warning("[Feedback] Signal emission failed (non-critical): %s", exc)


def get_feedback_for_query(db: Session, query_id: str) -> List[Feedback]:
    return (
        db.query(Feedback)
        .filter(Feedback.query_id == query_id)
        .order_by(Feedback.created_at.desc())
        .all()
    )
