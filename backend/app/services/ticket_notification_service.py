"""
Ticket Resolution Notification Service — Phase 2.10 & Enterprise In-App System
-------------------------------------------------------------------------------
Handles notifying users when their support tickets are resolved by a Domain Manager.
Includes notification payload construction (ticket number, original query, resolution,
resolution type, date resolved, link to ticket, re-run query in chat link).

Multi-channel delivery:
1. In-App Notification Center: durable record in `user_notifications` table.
2. Email Dispatcher: SMTP with rich HTML email template and plain text fallback.
3. Interactive Deep-links:
   - Direct Ticket Link: `${base_url}/tickets?ticket_id=...`
   - Re-run in Chat: `${base_url}/llm?q=...`

Resilience:
- Triggered only AFTER successful ticket resolution (database commit).
- If delivery fails: ticket remains RESOLVED, error is logged, no rollback occurs.
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.parse
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ticket import Ticket
from app.models.user_notification import UserNotification

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
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constructs the notification payload for a resolved ticket.
    Maintains 100% backward compatibility with Phase 2.10 tests while adding
    deep-linking and interactive RAG chat re-run capabilities.
    """
    effective_base_url = (base_url or getattr(settings, "frontend_base_url", "http://localhost:3000")).rstrip("/")
    resolved_date_str = (
        ticket.resolved_at.isoformat()
        if ticket.resolved_at
        else datetime.now(timezone.utc).isoformat()
    )
    ticket_link = f"{effective_base_url}/tickets/{ticket.ticket_id}"
    
    query_text = ticket.original_question or ""
    encoded_query = urllib.parse.quote(query_text)
    chat_rerun_link = f"{effective_base_url}/llm?q={encoded_query}"

    recipient = user_email or "user@domain.com"
    subject = f"Your Support Ticket #{ticket.ticket_id} Has Been Resolved"

    plain_message = (
        f"Hello,\n\n"
        f"Your support ticket #{ticket.ticket_id} has been resolved.\n\n"
        f"Ticket Number: {ticket.ticket_id}\n"
        f"Original Query: {ticket.original_question}\n"
        f"Resolution: {ticket.resolution}\n"
        f"Resolution Type: {ticket.resolution_type}\n"
        f"Date Resolved: {resolved_date_str}\n\n"
        f"Link: {ticket_link}\n"
        f"Re-run in Chat: {chat_rerun_link}\n\n"
        f"Thank you!"
    )

    html_message = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 24px; }}
    .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 28px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
    .header {{ border-bottom: 1px solid #f1f5f9; padding-bottom: 16px; margin-bottom: 20px; }}
    .badge {{ display: inline-block; padding: 4px 10px; background-color: #ecfdf5; color: #059669; border-radius: 9999px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
    .query-box {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 16px 0; border-radius: 4px; }}
    .resolution-box {{ background: #f0fdf4; border-left: 4px solid #10b981; padding: 14px 16px; margin: 16px 0; border-radius: 4px; }}
    .actions {{ margin-top: 24px; display: flex; gap: 12px; }}
    .btn {{ display: inline-block; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 13px; text-align: center; }}
    .btn-primary {{ background-color: #2563eb; color: #ffffff !important; }}
    .btn-secondary {{ background-color: #059669; color: #ffffff !important; }}
    .footer {{ margin-top: 24px; font-size: 11px; color: #94a3b8; text-align: center; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <span class="badge">Resolved</span>
      <h2 style="margin: 8px 0 0 0; color: #0f172a;">Ticket #{ticket.ticket_id} Solution Published</h2>
    </div>
    
    <p>Hello,</p>
    <p>A Domain Manager has reviewed and resolved your query escalation with verified knowledge.</p>

    <div class="query-box">
      <strong style="color: #475569; font-size: 12px;">ORIGINAL QUERY</strong>
      <div style="margin-top: 4px; font-size: 14px; color: #1e293b;">{ticket.original_question}</div>
    </div>

    <div class="resolution-box">
      <strong style="color: #047857; font-size: 12px;">EXPERT RESOLUTION</strong>
      <div style="margin-top: 4px; font-size: 14px; color: #064e3b; line-height: 1.5;">{ticket.resolution}</div>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 24px;">
      <tr>
        <td style="padding-right: 8px;">
          <a href="{chat_rerun_link}" class="btn btn-secondary" style="display:block; text-align:center;">💬 Re-run in Chat</a>
        </td>
        <td style="padding-left: 8px;">
          <a href="{ticket_link}" class="btn btn-primary" style="display:block; text-align:center;">📄 View Ticket</a>
        </td>
      </tr>
    </table>

    <div class="footer">
      This is an automated notification from Enterprise Knowledge Intelligence Platform.
    </div>
  </div>
</body>
</html>
"""

    payload = {
        "recipient_email": recipient,
        "ticket_number": ticket.ticket_id,
        "original_query": ticket.original_question or "",
        "resolution": ticket.resolution or "",
        "resolution_type": ticket.resolution_type or "TEXT",
        "date_resolved": resolved_date_str,
        "link": ticket_link,
        "rerun_link": chat_rerun_link,
        "subject": subject,
        "message": plain_message,
        "html_message": html_message,
    }
    return payload


def create_in_app_notification(
    db: Session,
    ticket: Ticket,
    payload: Dict[str, Any],
) -> Optional[UserNotification]:
    """
    Inserts a UserNotification record into the database for the user who raised the ticket.
    """
    if not ticket.user_id:
        logger.debug("[Notification] Ticket %s has no user_id, skipping in-app notification", ticket.ticket_id)
        return None

    try:
        title = f"Ticket #{ticket.ticket_id} Resolved"
        snippet = (ticket.resolution[:100] + "...") if ticket.resolution and len(ticket.resolution) > 100 else (ticket.resolution or "Your ticket has been marked as resolved.")
        message = f"Solution published for: '{ticket.original_question or ''}'. {snippet}"

        action_data = json.dumps({
            "ticket_id": ticket.ticket_id,
            "query": ticket.original_question,
            "resolution": ticket.resolution,
            "link": payload.get("link"),
            "rerun_link": payload.get("rerun_link"),
        })

        notif = UserNotification(
            user_id=ticket.user_id,
            ticket_id=ticket.ticket_id,
            title=title,
            message=message,
            type="success",
            action_type="ticket_resolved",
            action_data=action_data,
            read=False,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        logger.info(
            "[Notification] 🔔 Created In-App notification for user %s on ticket %s",
            ticket.user_id,
            ticket.ticket_id,
        )
        return notif
    except Exception as exc:
        logger.error("[Notification] Failed to create in-app notification: %s", exc)
        db.rollback()
        return None


def dispatch_smtp_email(payload: Dict[str, Any]) -> bool:
    """
    Dispatches an email via SMTP if settings.smtp_enabled is True.
    """
    if not getattr(settings, "smtp_enabled", False):
        logger.info(
            "[Notification] SMTP disabled or unconfigured. (Dev mode: email logged for %s)",
            payload.get("recipient_email"),
        )
        return True

    host = getattr(settings, "smtp_host", "localhost")
    port = int(getattr(settings, "smtp_port", 587))
    username = getattr(settings, "smtp_username", "")
    password = getattr(settings, "smtp_password", "")
    from_email = getattr(settings, "smtp_from_email", "support@enterprise-rag.com")
    from_name = getattr(settings, "smtp_from_name", "Enterprise RAG Intelligence")
    use_tls = getattr(settings, "smtp_use_tls", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = payload["subject"]
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = payload["recipient_email"]

    part1 = MIMEText(payload["message"], "plain")
    part2 = MIMEText(payload.get("html_message", payload["message"]), "html")
    msg.attach(part1)
    msg.attach(part2)

    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.sendmail(from_email, [payload["recipient_email"]], msg.as_string())

    logger.info("[Notification] 📧 Successfully dispatched SMTP email to %s", payload["recipient_email"])
    return True


def send_ticket_resolution_notification(
    ticket: Ticket,
    user_email: Optional[str] = None,
    base_url: str = "http://localhost:3000",
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Sends ticket resolution notification to the user via multi-channel (In-App + Email).
    MUST NOT raise exceptions to callers if delivery fails.
    """
    payload = format_resolution_notification(ticket, user_email=user_email, base_url=base_url)

    try:
        # 1. Custom dispatcher hook (used in unit tests)
        if _custom_dispatcher is not None:
            _custom_dispatcher(payload)
        else:
            # 2. In-App Notification Center
            if db is not None:
                create_in_app_notification(db, ticket, payload)

            # 3. SMTP Email Dispatcher
            dispatch_smtp_email(payload)

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
