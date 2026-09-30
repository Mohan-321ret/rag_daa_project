import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import Role
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token


def _new_user(role: Role, suffix: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{suffix}@ticket-api.test",
        full_name=role.value,
        hashed_password="test-hash",
        role=role.value,
        is_active=True,
    )


def _new_ticket(ticket_id: str, owner_id, *, domain: str, domain_id=None, manager_id=None) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id=owner_id,
        title=ticket_id,
        description="API authorization fixture",
        original_question=f"Question for {ticket_id}",
        generated_answer="Fixture answer",
        confidence_score=0.1,
        confidence_threshold=0.2,
        priority="low",
        domain=domain,
        status="open",
        routed_domain_id=domain_id,
        assigned_manager_id=manager_id,
        assigned_to=str(manager_id) if manager_id else None,
    )


@pytest.fixture
def ticket_api_case(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    user = _new_user(Role.STANDARD_EMPLOYEE, f"owner-{suffix}")
    other_user = _new_user(Role.STANDARD_EMPLOYEE, f"other-{suffix}")
    manager = _new_user(Role.DOMAIN_MANAGER, f"manager-{suffix}")
    domain = Domain(
        id=uuid.uuid4(),
        key=f"api-{suffix}",
        name=f"API Test {suffix}",
        is_active=True,
    )
    ticket_ids = {
        "own": f"TKT_API_OWN_{suffix}",
        "other": f"TKT_API_OTHER_{suffix}",
        "domain": f"TKT_API_DOMAIN_{suffix}",
        "assigned": f"TKT_API_ASSIGNED_{suffix}",
        "created": f"TKT_API_CREATED_{suffix}",
    }
    try:
        db.add_all([user, other_user, manager, domain])
        db.flush()
        db.add(UserDomain(user_id=manager.id, domain_id=domain.id, is_primary=True))
        db.add(
            DomainRoutingConfig(
                domain_id=domain.id,
                manager_user_id=manager.id,
                is_primary_manager=True,
                is_active=True,
            )
        )
        db.add_all(
            [
                _new_ticket(ticket_ids["own"], user.id, domain="General"),
                _new_ticket(ticket_ids["other"], other_user.id, domain="Finance"),
                _new_ticket(
                    ticket_ids["domain"],
                    other_user.id,
                    domain=domain.key,
                    domain_id=domain.id,
                ),
                _new_ticket(
                    ticket_ids["assigned"],
                    other_user.id,
                    domain="Finance",
                    manager_id=manager.id,
                ),
            ]
        )
        db.commit()

        user_token = create_access_token(str(user.id))
        other_token = create_access_token(str(other_user.id))
        manager_token = create_access_token(str(manager.id))
        client = TestClient(app)
        yield {
            "client": client,
            "user": user,
            "other_user": other_user,
            "manager": manager,
            "domain": domain,
            "ticket_ids": ticket_ids,
            "user_headers": {"Authorization": f"Bearer {user_token}"},
            "other_headers": {"Authorization": f"Bearer {other_token}"},
            "manager_headers": {"Authorization": f"Bearer {manager_token}"},
        }
    finally:
        db.rollback()
        db.query(Ticket).filter(Ticket.ticket_id.in_(ticket_ids.values())).delete(
            synchronize_session=False
        )
        db.query(Ticket).filter(
            Ticket.user_id.in_([user.id, other_user.id, manager.id])
        ).delete(synchronize_session=False)
        db.query(DomainRoutingConfig).filter(
            DomainRoutingConfig.manager_user_id == manager.id
        ).delete(synchronize_session=False)
        db.query(UserDomain).filter(UserDomain.user_id == manager.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id.in_([user.id, other_user.id, manager.id])).delete(
            synchronize_session=False
        )
        db.query(Domain).filter(Domain.id == domain.id).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_authentication_and_ownership_scoping(ticket_api_case):
    client = ticket_api_case["client"]
    ids = ticket_api_case["ticket_ids"]

    assert client.get("/api/v1/tickets/my").status_code == 401
    own = client.get("/api/v1/tickets/my", headers=ticket_api_case["user_headers"])
    assert own.status_code == 200
    assert {item["ticket_id"] for item in own.json()["tickets"]} == {ids["own"]}

    hidden_detail = client.get(
        f"/api/v1/tickets/{ids['other']}",
        headers=ticket_api_case["user_headers"],
    )
    assert hidden_detail.status_code == 404

    denied_manager_list = client.get(
        "/api/v1/tickets/manager",
        headers=ticket_api_case["user_headers"],
    )
    assert denied_manager_list.status_code == 403


def test_manager_scope_includes_only_domain_or_assigned_tickets(ticket_api_case):
    client = ticket_api_case["client"]
    ids = ticket_api_case["ticket_ids"]
    headers = ticket_api_case["manager_headers"]

    response = client.get("/api/v1/tickets/manager", headers=headers)
    assert response.status_code == 200
    returned = {item["ticket_id"] for item in response.json()["tickets"]}
    assert returned == {ids["domain"], ids["assigned"]}

    forbidden = client.get(f"/api/v1/tickets/{ids['other']}", headers=headers)
    assert forbidden.status_code == 404


def test_create_status_assign_and_resolve_apis(ticket_api_case):
    client = ticket_api_case["client"]
    user_headers = ticket_api_case["user_headers"]
    manager_headers = ticket_api_case["manager_headers"]
    ids = ticket_api_case["ticket_ids"]

    created = client.post(
        "/api/v1/tickets",
        headers=user_headers,
        json={
            "user_id": str(ticket_api_case["other_user"].id),
            "title": "My ticket",
            "description": "A test ticket",
            "original_question": "How do I request leave?",
            "generated_answer": "Contact HR.",
            "confidence_score": 0.4,
            "domain": ticket_api_case["domain"].key,
        },
    )
    assert created.status_code == 201
    assert created.json()["user_id"] == str(ticket_api_case["user"].id)

    invalid_status = client.put(
        f"/api/v1/tickets/{ids['own']}/status",
        headers=manager_headers,
        json={"status": "not-a-status"},
    )
    assert invalid_status.status_code == 422

    no_permission = client.put(
        f"/api/v1/tickets/{ids['other']}/status",
        headers=user_headers,
        json={"status": "resolved"},
    )
    assert no_permission.status_code == 403

    status_response = client.put(
        f"/api/v1/tickets/{ids['domain']}/status",
        headers=manager_headers,
        json={"status": "in_progress"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "in_progress"

    assignment = client.put(
        f"/api/v1/tickets/{ids['domain']}/assign",
        headers=manager_headers,
        json={"assigned_to": str(ticket_api_case["manager"].id)},
    )
    assert assignment.status_code == 200
    assert assignment.json()["assigned_manager_id"] == str(ticket_api_case["manager"].id)

    resolution = client.post(
        f"/api/v1/tickets/{ids['domain']}/resolve",
        headers=manager_headers,
        json={"resolution": "The leave request requires manager approval."},
    )
    assert resolution.status_code == 200
    assert resolution.json()["resolution"] == "The leave request requires manager approval."

    invalid_resolution = client.post(
        f"/api/v1/tickets/{ids['domain']}/resolve",
        headers=manager_headers,
        json={"resolution": "   "},
    )
    assert invalid_resolution.status_code in (400, 422)

