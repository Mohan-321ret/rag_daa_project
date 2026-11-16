import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import Role
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket, TicketStatus, ResolutionType, ResolutionFormat
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token


def _create_user(role: Role, suffix: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{suffix}@phase26.test",
        full_name=f"User {role.value} {suffix}",
        hashed_password="test-password-hash",
        role=role.value,
        is_active=True,
    )


def _create_ticket(
    ticket_id: str,
    owner_id: uuid.UUID,
    *,
    domain: str = "General",
    domain_id: uuid.UUID = None,
    manager_id: uuid.UUID = None,
    status: str = "open",
    resolution: str = None,
    resolution_type: str = None,
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id=owner_id,
        title=f"Support Ticket {ticket_id}",
        description="Low confidence RAG answer requiring resolution",
        original_question="What is the remote work policy?",
        generated_answer="The remote work policy allows 2 days remote work.",
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
    )


@pytest.fixture
def resolution_test_env(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    owner_user = _create_user(Role.STANDARD_EMPLOYEE, f"owner-{suffix}")
    other_user = _create_user(Role.STANDARD_EMPLOYEE, f"other-{suffix}")
    manager_user = _create_user(Role.DOMAIN_MANAGER, f"manager-{suffix}")
    unauthorized_manager = _create_user(Role.DOMAIN_MANAGER, f"unauth-{suffix}")

    domain = Domain(
        id=uuid.uuid4(),
        key=f"domain-{suffix}",
        name=f"Domain {suffix}",
        is_active=True,
    )
    other_domain = Domain(
        id=uuid.uuid4(),
        key=f"otherdomain-{suffix}",
        name=f"Other Domain {suffix}",
        is_active=True,
    )

    tkt_open_id = f"TKT_P26_OPEN_{suffix}"
    tkt_resolved_id = f"TKT_P26_RESOLVED_{suffix}"

    try:
        db.add_all([owner_user, other_user, manager_user, unauthorized_manager, domain, other_domain])
        db.flush()

        db.add(UserDomain(user_id=manager_user.id, domain_id=domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=domain.id, manager_user_id=manager_user.id, is_active=True))

        db.add(UserDomain(user_id=unauthorized_manager.id, domain_id=other_domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=other_domain.id, manager_user_id=unauthorized_manager.id, is_active=True))

        tkt_open = _create_ticket(
            tkt_open_id,
            owner_user.id,
            domain=domain.name,
            domain_id=domain.id,
            manager_id=manager_user.id,
            status="open",
        )
        tkt_resolved = _create_ticket(
            tkt_resolved_id,
            owner_user.id,
            domain=domain.name,
            domain_id=domain.id,
            manager_id=manager_user.id,
            status="resolved",
            resolution="Prior verified resolution.",
            resolution_type="TEXT",
        )

        db.add_all([tkt_open, tkt_resolved])
        db.commit()

        manager_token = create_access_token(str(manager_user.id))
        owner_token = create_access_token(str(owner_user.id))
        unauth_token = create_access_token(str(unauthorized_manager.id))

        yield {
            "db": db,
            "owner": owner_user,
            "manager": manager_user,
            "unauthorized_manager": unauthorized_manager,
            "manager_token": manager_token,
            "owner_token": owner_token,
            "unauth_token": unauth_token,
            "open_ticket_id": tkt_open_id,
            "resolved_ticket_id": tkt_resolved_id,
        }
    finally:
        db.close()


def test_1_valid_text_resolution(resolution_test_env):
    """Test 1: Valid resolution submission by authorized Domain Manager."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["open_ticket_id"]

    resolution_text = "The updated policy allows full remote work up to 3 days per week with manager approval."

    response = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={
            "resolution": resolution_text,
            "resolution_type": "TEXT",
            "internal_notes": "Verified against HR Policy Section 4",
        },
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert data["ticket_id"] == ticket_id
    assert data["status"] == "resolved"
    assert data["resolution"] == resolution_text
    assert data["resolution_type"] == "TEXT"
    assert data["resolved_at"] is not None


def test_2_empty_resolution_validation(resolution_test_env):
    """Test 2: Submitting empty or whitespace-only resolution returns 400 Bad Request."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["open_ticket_id"]

    # Test empty string
    res_empty = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "", "resolution_type": "TEXT"},
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res_empty.status_code in (400, 422), f"Expected 400/422 for empty resolution, got {res_empty.status_code}"

    # Test whitespace-only string
    res_ws = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "    ", "resolution_type": "TEXT"},
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res_ws.status_code in (400, 422), f"Expected 400/422 for whitespace resolution, got {res_ws.status_code}"


def test_3_unauthorized_manager_resolution(resolution_test_env):
    """Test 3: Standard user or unauthorized manager cannot resolve ticket."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["open_ticket_id"]

    # Owner (Standard employee without TICKET_RESOLVE permission)
    res_owner = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "Attempting owner self-resolution"},
        headers={"Authorization": f"Bearer {env['owner_token']}"},
    )
    assert res_owner.status_code in (403, 404), f"Expected 403/404 for standard user, got {res_owner.status_code}"

    # Unauthorized Manager (outside authorized domain)
    res_unauth = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "Attempting cross-domain manager resolution"},
        headers={"Authorization": f"Bearer {env['unauth_token']}"},
    )
    assert res_unauth.status_code in (403, 404), f"Expected 403/404 for unauth manager, got {res_unauth.status_code}"


def test_4_already_resolved_ticket(resolution_test_env):
    """Test 4: Attempting to resolve an already resolved ticket returns 400 Bad Request."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["resolved_ticket_id"]

    res_already = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "Attempting duplicate resolution"},
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )

    assert res_already.status_code == 400, f"Expected 400 for already resolved ticket, got {res_already.status_code}"
    detail = res_already.json().get("detail", "")
    assert "already resolved" in detail.lower() or "resolved" in detail.lower()


def test_5_correct_resolution_storage(resolution_test_env):
    """Test 5: Verifies database storage of resolution, resolution_type, resolver_id, and timestamps."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["open_ticket_id"]
    db = env["db"]

    resolution_text = "Authoritative text resolution for storage verification."

    res = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": resolution_text, "resolution_type": "TEXT"},
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res.status_code == 200

    db.expire_all()
    ticket_row = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    assert ticket_row is not None
    assert ticket_row.resolution == resolution_text
    assert ticket_row.resolution_type == "TEXT"
    assert ticket_row.resolution_format == "TEXT"
    assert ticket_row.status == "resolved"
    assert ticket_row.resolved_at is not None
    assert ticket_row.updated_at is not None
    assert str(ticket_row.resolver_user_id) == str(env["manager"].id)


def test_6_correct_status_update_and_field_preservation(resolution_test_env):
    """Test 6: Verifies status is updated to RESOLVED while preserving original query, answer, and confidence."""
    client = TestClient(app)
    env = resolution_test_env
    ticket_id = env["open_ticket_id"]
    db = env["db"]

    # Record initial field values
    db.expire_all()
    initial_ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    orig_q = initial_ticket.original_question
    orig_ans = initial_ticket.generated_answer
    orig_conf = initial_ticket.confidence_score
    orig_user_id = initial_ticket.user_id

    # Execute resolution
    res = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        json={"resolution": "Verified text answer preserving metadata."},
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res.status_code == 200

    db.expire_all()
    after_ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()

    # Status check
    assert after_ticket.status == "resolved"

    # Preserved fields check
    assert after_ticket.original_question == orig_q
    assert after_ticket.generated_answer == orig_ans
    assert after_ticket.confidence_score == orig_conf
    assert after_ticket.user_id == orig_user_id

    # User visibility check: Owner can view ticket resolution
    owner_get = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {env['owner_token']}"},
    )
    assert owner_get.status_code == 200
    owner_data = owner_get.json()
    assert owner_data["status"] == "resolved"
    assert owner_data["resolution"] == "Verified text answer preserving metadata."
