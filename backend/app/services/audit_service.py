"""
Audit Service  –  User, Domain & Access Management
--------------------------------------------------------
Single write path for the audit trail (app/models/audit_log.py). Every
sensitive User & Access Management mutation in app/api/users.py and
app/api/domains.py calls log_audit_event() — never writes AuditLog rows
directly, so the shape/behavior (never raises, always logs the outcome)
stays consistent everywhere.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


def log_audit_event(
    db: Session,
    *,
    event_type: str,
    actor: User,
    target: Optional[User] = None,
    before: Optional[str] = None,
    after: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """
    Record one audit event. Best-effort: a logging failure must never break
    the admin action it's describing, so this swallows (and logs) errors
    rather than raising — mirrors ticket_service.maybe_create_ticket's
    never-break-the-caller contract.
    """
    try:
        row = AuditLog(
            event_type=event_type,
            actor_id=actor.id,
            actor_email=actor.email,
            target_user_id=target.id if target else None,
            target_email=target.email if target else None,
            before_value=before,
            after_value=after,
            detail=detail,
        )
        db.add(row)
        db.flush()  # let the caller's own commit persist this alongside its change
        logger.info(
            "[Audit] 📋 %s | actor=%s target=%s | %s -> %s",
            event_type, actor.email, target.email if target else "-", before, after,
        )
    except Exception as exc:
        logger.error("[Audit] Failed to record %s event: %s", event_type, exc)
