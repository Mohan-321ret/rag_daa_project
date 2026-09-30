"""
Unit and Integration Tests for Phase 2.10: Ticket Resolution Notification
-------------------------------------------------------------------------
Tests:
1. Notification Content Structure (ticket number, original query, resolution, resolution type, date resolved, link)
2. Successful Notification Delivery upon Ticket Resolution
3. Notification Failure Resilience (Ticket remains RESOLVED, error is logged, no rollback of resolution)
4. Delivery timing (triggered only after ticket resolution commit)
"""
import logging
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import Role
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.ticket import Ticket, TicketStatus, ResolutionType
from app.models.user import User
from app.services.auth_service import create_access_token
from app.services.ticket_notification_service import (
    format_resolution_notification,
    send_ticket_resolution_notification,
    set_custom_dispatcher,
)
from app.services.ticket_service import resolve_ticket


def _create_test_user(db, role: Role, email_prefix: str) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"{email_prefix}_{uuid.uuid4().hex[:6]}@example.com",
        full_name=f"Test {role.value}",
        hashed_password="test-hash",
        role=role.value,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create_test_ticket(db, user_id: uuid.UUID, domain: str = "General") -> Ticket:
    t = Ticket(
        ticket_id=f"TKT_NOTIF_{uuid.uuid4().hex[:8].upper()}",
        user_id=user_id,
        title="Password Reset Help",
        description="User cannot log in",
        original_question="How do I reset my account password?",
        generated_answer="Contact system admin.",
        confidence_score=0.2,
        domain=domain,
        status=TicketStatus.OPEN.value,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture(autouse=True)
def reset_dispatcher():
    set_custom_dispatcher(None)
    yield
    set_custom_dispatcher(None)


def test_notification_payload_formatting():
    """Verify notification format contains all required fields."""
    ticket = Ticket(
        ticket_id="TKT_123456",
        original_question="How to apply for leave?",
        resolution="Submit leave form via HR portal.",
        resolution_type=ResolutionType.TEXT.value,
        resolved_at=datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc),
    )
    payload = format_resolution_notification(ticket, user_email="employee@company.com")

    assert payload["ticket_number"] == "TKT_123456"
    assert payload["original_query"] == "How to apply for leave?"
    assert payload["resolution"] == "Submit leave form via HR portal."
    assert payload["resolution_type"] == "TEXT"
    assert "2026-09-30" in payload["date_resolved"]
    assert "/tickets/TKT_123456" in payload["link"]
    assert payload["recipient_email"] == "employee@company.com"
    assert "TKT_123456" in payload["subject"]
    assert payload["resolution"] in payload["message"]


def test_successful_notification_delivery():
    """Test resolving a ticket dispatches notification successfully to user."""
    init_db()
    db = SessionLocal()
    received_notifications = []

    def mock_dispatcher(payload):
        received_notifications.append(payload)

    set_custom_dispatcher(mock_dispatcher)

    try:
        user = _create_test_user(db, Role.STANDARD_EMPLOYEE, "notif_user")
        manager = _create_test_user(db, Role.DOMAIN_MANAGER, "notif_mgr")
        ticket = _create_test_ticket(db, user.id)

        resolved_ticket = resolve_ticket(
            db=db,
            ticket_id=ticket.ticket_id,
            resolution="Use self-service portal link for password reset.",
            current_user=manager,
            caller_role=Role.DOMAIN_MANAGER,
            resolution_type="TEXT",
        )

        assert resolved_ticket is not None
        assert resolved_ticket.status == TicketStatus.RESOLVED.value
        assert len(received_notifications) == 1

        notif = received_notifications[0]
        assert notif["ticket_number"] == ticket.ticket_id
        assert notif["recipient_email"] == user.email
        assert notif["original_query"] == "How do I reset my account password?"
        assert notif["resolution"] == "Use self-service portal link for password reset."
        assert notif["resolution_type"] == "TEXT"
        assert notif["link"].endswith(f"/tickets/{ticket.ticket_id}")

    finally:
        db.close()


def test_notification_failure_resilience(caplog):
    """
    Test that when notification delivery fails (e.g. SMTP/network error):
    1. Ticket remains RESOLVED.
    2. Notification failure is logged.
    3. Resolution text and state are NOT rolled back.
    """
    init_db()
    db = SessionLocal()

    def failing_dispatcher(payload):
        raise RuntimeError("SMTP Server Unavailable: 554 Delivery Failed")

    set_custom_dispatcher(failing_dispatcher)

    try:
        user = _create_test_user(db, Role.STANDARD_EMPLOYEE, "fail_notif_user")
        manager = _create_test_user(db, Role.DOMAIN_MANAGER, "fail_notif_mgr")
        ticket = _create_test_ticket(db, user.id)

        with caplog.at_level(logging.ERROR):
            resolved_ticket = resolve_ticket(
                db=db,
                ticket_id=ticket.ticket_id,
                resolution="Reset link dispatched via SMS.",
                current_user=manager,
                caller_role=Role.DOMAIN_MANAGER,
                resolution_type="TEXT",
            )

        # 1. Ticket MUST be resolved
        assert resolved_ticket is not None
        assert resolved_ticket.status == TicketStatus.RESOLVED.value
        assert resolved_ticket.resolution == "Reset link dispatched via SMS."

        # Verify DB persisted state
        db_ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket.ticket_id).first()
        assert db_ticket is not None
        assert db_ticket.status == TicketStatus.RESOLVED.value
        assert db_ticket.resolution == "Reset link dispatched via SMS."

        # 2. Failure MUST be logged
        assert any(
            "Failed to deliver resolution notification" in record.message
            or "Failed to send ticket resolution notification" in record.message
            for record in caplog.records
        )


    finally:
        db.close()


def test_api_resolution_triggers_notification():
    """Test resolution via API endpoint triggers notification."""
    init_db()
    db = SessionLocal()
    received_notifications = []

    def mock_dispatcher(payload):
        received_notifications.append(payload)

    set_custom_dispatcher(mock_dispatcher)

    try:
        user = _create_test_user(db, Role.STANDARD_EMPLOYEE, "api_user")
        manager = _create_test_user(db, Role.DOMAIN_MANAGER, "api_mgr")
        ticket = _create_test_ticket(db, user.id, domain="IT")

        mgr_token = create_access_token(str(manager.id))
        client = TestClient(app)

        res = client.post(
            f"/api/v1/tickets/{ticket.ticket_id}/resolve",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={
                "resolution": "Resolved via IT Service Desk portal.",
                "resolution_type": "TEXT",
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "resolved"

        assert len(received_notifications) == 1
        assert received_notifications[0]["ticket_number"] == ticket.ticket_id
        assert received_notifications[0]["recipient_email"] == user.email

    finally:
        db.close()
