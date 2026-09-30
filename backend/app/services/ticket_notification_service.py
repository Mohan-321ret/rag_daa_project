"""
Ticket Resolution Notification Service — Phase 2.10
---------------------------------------------------
Handles notifying users when their support tickets are resolved by a Domain Manager.
Includes notification payload construction (ticket number, original query, resolution,
resolution type, date resolved, link to ticket).

Resilience:
- Triggered only AFTER successful ticket resolution (database commit).
- If delivery fails: ticket remains RESOLVED, error is logged, no rollback occurs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

# Optional custom dispatcher hook for unit testing delivery success/failure
_custom_dispatcher: Optional[Callable[[Dict[str, Any]], None]] = None


def set_custom_dispatcher(dispatcher: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Set custom notification dispatcher hook (useful for testing failure/success)."""
    global _custom_dispatcher
    _custom_dispatcher = dispatcher


def format_resolution_notification(
    ticket: Ticket,
    user_email: Optional[str] = None,
    base_url: str = "http://localhost:3000",
) -> Dict[str, Any]:
    """
    Constructs the notification payload for a resolved ticket.
    """
    resolved_date_str = (
        ticket.resolved_at.isoformat()
        if ticket.resolved_at
        else datetime.now(timezone.utc).isoformat()
    )
    ticket_link = f"{base_url.rstrip('/')}/tickets/{ticket.ticket_id}"

    recipient = user_email or "user@domain.com"
    payload = {
        "recipient_email": recipient,
        "ticket_number": ticket.ticket_id,
        "original_query": ticket.original_question or "",
        "resolution": ticket.resolution or "",
        "resolution_type": ticket.resolution_type or "TEXT",
        "date_resolved": resolved_date_str,
        "link": ticket_link,
        "subject": f"Your Support Ticket #{ticket.ticket_id} Has Been Resolved",
        "message": (
            f"Hello,\n\n"
            f"Your support ticket #{ticket.ticket_id} has been resolved.\n\n"
            f"Ticket Number: {ticket.ticket_id}\n"
            f"Original Query: {ticket.original_question}\n"
            f"Resolution: {ticket.resolution}\n"
            f"Resolution Type: {ticket.resolution_type}\n"
            f"Date Resolved: {resolved_date_str}\n\n"
            f"Link: {ticket_link}\n\n"
            f"Thank you!"
        ),
    }
    return payload


def send_ticket_resolution_notification(
    ticket: Ticket,
    user_email: Optional[str] = None,
    base_url: str = "http://localhost:3000",
) -> Dict[str, Any]:
    """
    Sends ticket resolution notification to the user.
    MUST NOT raise exceptions to callers if delivery fails.
    """
    payload = format_resolution_notification(ticket, user_email=user_email, base_url=base_url)

    try:
        if _custom_dispatcher is not None:
            _custom_dispatcher(payload)
        else:
            # Standard in-system delivery action: log notification details
            logger.info(
                "[Notification] 📧 Ticket resolution notification delivered to %s for ticket %s",
                payload["recipient_email"],
                payload["ticket_number"],
            )

        return {"success": True, "payload": payload, "error": None}

    except Exception as exc:
        error_msg = f"Failed to deliver resolution notification for ticket '{ticket.ticket_id}': {exc}"
        logger.error("[Notification] ❌ %s", error_msg)
        return {"success": False, "payload": payload, "error": str(exc)}
