"""
Phase 2.9: User Ticket Interface — Integration Test Suite
-----------------------------------------------------------
Tests user ticket interface display, detail viewing, and access restrictions:
1. List user tickets (GET /api/v1/tickets/my returns user's low-confidence query tickets with required fields)
2. View single ticket detail (GET /api/v1/tickets/{ticket_id} returns query, AI answer, confidence, status, domain, resolution, and KB attachment info)
3. Access Restrictions & Authorization:
   - User CANNOT modify tickets (PATCH returns 403 Forbidden)
   - User CANNOT resolve tickets (POST /resolve returns 403 Forbidden)
   - User CANNOT access another user's ticket (GET returns 404/403)
   - Internal manager-only triage notes (internal_notes, reviewer_notes) are sanitized/hidden for standard users
"""
import io
import uuid
import pytest
from docx import Document as DocxBuilder
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import Role
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.document import Document
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket, TicketStatus, ResolutionType, ResolutionFormat
from app.models.ticket_attachment import TicketAttachment, TicketAttachmentStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token


def _create_user(role: Role, suffix: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{suffix}@phase29.test",
        full_name=f"User {role.value} {suffix}",
        hashed_password="test-password-hash",
        role=role.value,
        is_active=True,
    )


def _create_ticket(
    ticket_id: str,
    owner_id: uuid.UUID,
    *,
    domain: str = "HR",
    domain_id: uuid.UUID = None,
    manager_id: uuid.UUID = None,
    status: str = "open",
    resolution: str = None,
    resolution_type: str = None,
    resolved_at = None,
    internal_notes: str = None,
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id=owner_id,
        title=f"Low Confidence Escalation {ticket_id}",
        description="Low confidence query escalated to support ticket",
        original_question="What is the parental leave duration policy for 2026?",
        generated_answer="Parental leave is 12 weeks for primary caregivers.",
        confidence_score=0.35,
        confidence_threshold=0.50,
        priority="medium",
        domain=domain,
        routed_domain_id=domain_id,
        assigned_manager_id=manager_id,
        assigned_to=str(manager_id) if manager_id else None,
        status=status,
        resolution=resolution,
        resolution_type=resolution_type,
        resolved_at=resolved_at,
        internal_notes=internal_notes,
        feedback=internal_notes,
    )


def _generate_docx_bytes(content: str) -> bytes:
    doc = DocxBuilder()
    doc.add_heading("Parental Leave Policy 2026", 0)
    doc.add_paragraph(content)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def p29_test_env(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    user_a = _create_user(Role.STANDARD_EMPLOYEE, f"usera-{suffix}")
    user_b = _create_user(Role.STANDARD_EMPLOYEE, f"userb-{suffix}")
    manager_user = _create_user(Role.DOMAIN_MANAGER, f"manager-{suffix}")

    domain = Domain(
        id=uuid.uuid4(),
        key=f"dom-hr-{suffix}",
        name=f"HR Domain {suffix}",
        is_active=True,
    )

    tkt_a_id = f"TKT_P29_USERA_{suffix}"
    tkt_b_id = f"TKT_P29_USERB_{suffix}"

    try:
        db.add_all([user_a, user_b, manager_user, domain])
        db.flush()

        db.add(UserDomain(user_id=manager_user.id, domain_id=domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=domain.id, manager_user_id=manager_user.id, is_active=True))

        tkt_a = _create_ticket(
            tkt_a_id,
            user_a.id,
            domain="HR",
            domain_id=domain.id,
            manager_id=manager_user.id,
            status="open",
            internal_notes="Internal manager notes: user query needs policy doc review.",
        )
        tkt_b = _create_ticket(
            tkt_b_id,
            user_b.id,
            domain="HR",
            domain_id=domain.id,
            manager_id=manager_user.id,
            status="open",
        )
        db.add_all([tkt_a, tkt_b])
        db.commit()

        user_a_token = create_access_token(str(user_a.id))
        user_b_token = create_access_token(str(user_b.id))
        manager_token = create_access_token(str(manager_user.id))

        yield {
            "db": db,
            "user_a": user_a,
            "user_b": user_b,
            "manager": manager_user,
            "user_a_token": user_a_token,
            "user_b_token": user_b_token,
            "manager_token": manager_token,
            "tkt_a_id": tkt_a_id,
            "tkt_b_id": tkt_b_id,
            "domain_id": domain.id,
            "suffix": suffix,
        }
    finally:
        db.close()


def test_1_user_list_own_tickets(p29_test_env):
    """
    Test 1: Standard user lists their own tickets via GET /api/v1/tickets/my.
    Must return tickets owned by user with required fields (ticket_number, original_question, confidence_score, domain, status, created_at, resolution, resolved_at).
    """
    client = TestClient(app)
    env = p29_test_env
    headers = {"Authorization": f"Bearer {env['user_a_token']}"}

    res = client.get("/api/v1/tickets/my", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] >= 1
    tkt = next((t for t in data["tickets"] if t["ticket_id"] == env["tkt_a_id"]), None)
    assert tkt is not None

    # Verify all required display fields are present
    assert tkt["ticket_id"] == env["tkt_a_id"]
    assert "parental leave" in (tkt["original_question"] or tkt["user_question"] or tkt["query_text"]).lower()
    assert tkt["confidence_score"] == 0.35
    assert tkt["domain"] == "HR"
    assert tkt["status"] == "open"
    assert tkt["created_at"] is not None


def test_2_user_view_ticket_detail_and_kb_info(p29_test_env):
    """
    Test 2: Standard user opens single ticket detail and views query, answer, confidence, status, domain, resolution, and attached KB docs.
    """
    client = TestClient(app)
    env = p29_test_env
    db = env["db"]
    headers_mgr = {"Authorization": f"Bearer {env['manager_token']}"}
    headers_user = {"Authorization": f"Bearer {env['user_a_token']}"}
    tkt_id = env["tkt_a_id"]

    # 1. Manager uploads a KB document to ticket A
    docx_bytes = _generate_docx_bytes("Parental leave policy document 2026.")
    upload_res = client.post(
        f"/api/v1/tickets/{tkt_id}/upload-kb?sync=true",
        headers=headers_mgr,
        files={"file": ("ParentalLeave2026.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert upload_res.status_code == 202
    attachment_id = upload_res.json()["attachment_id"]

    # 2. Manager resolves ticket A
    resolve_res = client.post(
        f"/api/v1/tickets/{tkt_id}/resolve",
        headers=headers_mgr,
        json={
            "resolution": "Approved 16 weeks paid parental leave policy for 2026.",
            "resolution_type": "BOTH",
            "attachment_id": attachment_id,
        },
    )
    assert resolve_res.status_code == 200

    # 3. User A views single ticket detail
    res = client.get(f"/api/v1/tickets/{tkt_id}", headers=headers_user)
    assert res.status_code == 200, res.text
    detail = res.json()

    assert detail["ticket_id"] == tkt_id
    assert "parental leave" in (detail["original_question"] or detail["query_text"]).lower()
    assert detail["generated_answer"] is not None
    assert detail["confidence_score"] == 0.35
    assert detail["status"] == "resolved"
    assert detail["domain"] == "HR"
    assert "Approved 16 weeks paid parental leave policy" in detail["resolution"]
    assert detail["resolved_at"] is not None

    # Verify KB document information is present in attachments
    assert "attachments" in detail
    assert len(detail["attachments"]) >= 1
    att = detail["attachments"][0]
    assert att["original_filename"] == "ParentalLeave2026.docx"
    assert att["status"] == "COMPLETED"


def test_3_user_cannot_modify_or_resolve_tickets(p29_test_env):
    """
    Test 3: Standard user CANNOT modify tickets or manager resolutions.
    PATCH /tickets/{id} and POST /tickets/{id}/resolve return 403 Forbidden.
    """
    client = TestClient(app)
    env = p29_test_env
    headers_user = {"Authorization": f"Bearer {env['user_a_token']}"}
    tkt_id = env["tkt_a_id"]

    # Attempt ticket update -> Expect 403
    patch_res = client.patch(
        f"/api/v1/tickets/{tkt_id}",
        headers=headers_user,
        json={"priority": "critical"},
    )
    assert patch_res.status_code == 403

    # Attempt ticket resolution -> Expect 403
    resolve_res = client.post(
        f"/api/v1/tickets/{tkt_id}/resolve",
        headers=headers_user,
        json={"resolution": "Unauthorized resolution attempt."},
    )
    assert resolve_res.status_code == 403


def test_4_user_cannot_access_other_users_tickets(p29_test_env):
    """
    Test 4: Standard user A CANNOT access User B's tickets (GET /tickets/{user_b_ticket} returns 404/403).
    """
    client = TestClient(app)
    env = p29_test_env
    headers_user_a = {"Authorization": f"Bearer {env['user_a_token']}"}
    tkt_b_id = env["tkt_b_id"]

    # User A tries to view User B's ticket
    res = client.get(f"/api/v1/tickets/{tkt_b_id}", headers=headers_user_a)
    assert res.status_code in (404, 403)


def test_5_internal_notes_hidden_from_users(p29_test_env):
    """
    Test 5: Internal manager triage notes (internal_notes, reviewer_notes) are hidden/sanitized for standard users.
    """
    client = TestClient(app)
    env = p29_test_env
    headers_user_a = {"Authorization": f"Bearer {env['user_a_token']}"}
    tkt_a_id = env["tkt_a_id"]

    res = client.get(f"/api/v1/tickets/{tkt_a_id}", headers=headers_user_a)
    assert res.status_code == 200
    detail = res.json()

    # Verify manager internal notes are sanitized (None or absent)
    assert detail.get("internal_notes") is None
    assert detail.get("reviewer_notes") is None
