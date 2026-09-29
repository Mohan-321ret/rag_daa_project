"""Assign low-confidence tickets to configured domain managers."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.domain import Domain
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.services.domain_router_service import classify_domain_sync, get_domain_managers

logger = logging.getLogger(__name__)


def assign_ticket_to_domain_manager(
    db: Session,
    ticket: Ticket,
    *,
    query_text: str,
    user_id: Optional[str] = None,
    intent: Optional[str] = None,
    entities: Optional[list] = None,
    source_document_ids: Optional[list[str]] = None,
    explicit_domain: Optional[str] = None,
) -> Optional[User]:
    """Classify a ticket and assign its active domain's primary manager.

    The ticket remains OPEN whether assignment succeeds or not. A domain or
    manager is never inferred from a default placeholder such as "General".
    """
    now = datetime.now(timezone.utc)
    ticket.status = TicketStatus.OPEN.value
    ticket.assigned_manager_id = None
    ticket.assigned_to = None
    ticket.assigned_at = None

    try:
        result = classify_domain_sync(
            db,
            query_text=query_text,
            # Ticket assignment follows query/source evidence, not the user's
            # membership domain, which may be unrelated to this request.
            user_id=None,
            intent=intent,
            entities=entities,
            source_document_ids=source_document_ids,
            explicit_domain=explicit_domain,
        )
        ticket.routing_confidence = result.confidence
        ticket.routing_method = result.method
        ticket.routing_timestamp = now
        ticket.needs_triage = result.needs_triage

        if result.domain_id is None:
            logger.warning(
                "[TicketAssignment] No valid domain identified for ticket %s; leaving OPEN and unassigned.",
                ticket.ticket_id,
            )
            return None

        domain = (
            db.query(Domain)
            .filter(Domain.id == result.domain_id, Domain.is_active.is_(True))
            .first()
        )
        if domain is None:
            logger.warning(
                "[TicketAssignment] Domain %s is missing or inactive for ticket %s; leaving OPEN and unassigned.",
                result.domain_id,
                ticket.ticket_id,
            )
            ticket.needs_triage = True
            return None

        ticket.routed_domain_id = domain.id
        ticket.domain = domain.key

        managers = [
            manager
            for manager in get_domain_managers(db, domain.id)
            if manager.is_active and manager.role == Role.DOMAIN_MANAGER.value
        ]
        if not managers:
            logger.warning(
                "[TicketAssignment] No active Domain Manager configured for domain '%s' (ticket %s); leaving OPEN and unassigned.",
                domain.key,
                ticket.ticket_id,
            )
            ticket.needs_triage = True
            return None

        manager = managers[0]
        ticket.assigned_manager_id = manager.id
        ticket.assigned_to = str(manager.id)
        ticket.assigned_at = now
        ticket.needs_triage = False
        ticket.updated_at = now
        logger.info(
            "[TicketAssignment] Assigned ticket %s to Domain Manager %s for domain '%s'.",
            ticket.ticket_id,
            manager.id,
            domain.key,
        )
        return manager
    except Exception:
        ticket.status = TicketStatus.OPEN.value
        ticket.assigned_manager_id = None
        ticket.assigned_to = None
        ticket.assigned_at = None
        ticket.needs_triage = True
        logger.exception(
            "[TicketAssignment] Routing failed for ticket %s; leaving OPEN and unassigned.",
            ticket.ticket_id,
        )
        return None
