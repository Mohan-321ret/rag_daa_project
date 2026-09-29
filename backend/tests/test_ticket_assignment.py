import uuid
from types import SimpleNamespace

from app.core.permissions import Role
from app.models import chunk
from app.models.domain import Domain
from app.models.ticket import Ticket
from app.services import domain_router_service, ticket_assignment_service
from app.services import ticket_service


class FakeQuery:
    def __init__(self, row=None):
        self.row = row

    def filter(self, *args):
        return self

    def first(self):
        return self.row


class FakeDatabase:
    def __init__(self, domain=None):
        self.domain = domain

    def query(self, model):
        if model is Domain:
            return FakeQuery(self.domain)
        if model is Ticket:
            return FakeQuery()
        raise AssertionError(f"Unexpected model queried: {model}")

    def add(self, row):
        self.added = row

    def flush(self):
        pass

    def commit(self):
        pass

    def refresh(self, row):
        pass

    def rollback(self):
        pass


def _ticket():
    return SimpleNamespace(
        ticket_id="TKT_ASSIGN_TEST",
        domain="General",
        status="open",
        assigned_manager_id=None,
        assigned_to=None,
        assigned_at=None,
        routed_domain_id=None,
        routing_confidence=None,
        routing_method=None,
        routing_timestamp=None,
        needs_triage=False,
        updated_at=None,
    )


def test_query_identifies_hr_domain():
    domain = SimpleNamespace(id=uuid.uuid4(), key="hr", name="Human Resources", is_active=True)
    result = domain_router_service.classify_domain_sync(
        FakeDatabase(domain),
        query_text="How do I request annual leave?",
    )

    assert result.domain_id == domain.id
    assert result.domain_key == "hr"
    assert result.method == "intent_keywords"


def test_ticket_assigned_to_active_domain_manager(monkeypatch):
    domain = SimpleNamespace(id=uuid.uuid4(), key="finance", name="Finance", is_active=True)
    manager = SimpleNamespace(
        id=uuid.uuid4(),
        role=Role.DOMAIN_MANAGER.value,
        is_active=True,
    )
    monkeypatch.setattr(
        ticket_assignment_service,
        "get_domain_managers",
        lambda db, domain_id: [manager],
    )

    ticket = _ticket()
    assigned = ticket_assignment_service.assign_ticket_to_domain_manager(
        FakeDatabase(domain),
        ticket,
        query_text="How do I submit an expense invoice?",
    )

    assert assigned is manager
    assert ticket.domain == "finance"
    assert ticket.routed_domain_id == domain.id
    assert ticket.assigned_manager_id == manager.id
    assert ticket.assigned_to == str(manager.id)
    assert ticket.status == "open"


def test_no_domain_manager_leaves_ticket_open_and_unassigned(monkeypatch, caplog):
    domain = SimpleNamespace(id=uuid.uuid4(), key="it", name="IT", is_active=True)
    monkeypatch.setattr(
        ticket_assignment_service, "get_domain_managers", lambda db, domain_id: []
    )
    ticket = _ticket()

    assigned = ticket_assignment_service.assign_ticket_to_domain_manager(
        FakeDatabase(domain), ticket, query_text="My laptop cannot connect to VPN"
    )

    assert assigned is None
    assert ticket.status == "open"
    assert ticket.assigned_manager_id is None
    assert ticket.assigned_to is None
    assert ticket.needs_triage is True
    assert "No active Domain Manager" in caplog.text


def test_invalid_domain_does_not_assign_manager(monkeypatch, caplog):
    invalid_id = uuid.uuid4()
    monkeypatch.setattr(
        ticket_assignment_service,
        "classify_domain_sync",
        lambda *args, **kwargs: domain_router_service.DomainRoutingResult(
            domain_key="finance",
            domain_id=invalid_id,
            confidence=0.9,
            method="intent_keywords",
            needs_triage=False,
            reasoning="test invalid domain",
        ),
    )
    monkeypatch.setattr(
        ticket_assignment_service,
        "get_domain_managers",
        lambda *args, **kwargs: [SimpleNamespace(id=uuid.uuid4(), role=Role.DOMAIN_MANAGER.value, is_active=True)],
    )
    ticket = _ticket()

    assigned = ticket_assignment_service.assign_ticket_to_domain_manager(
        FakeDatabase(domain=None), ticket, query_text="invoice approval"
    )

    assert assigned is None
    assert ticket.status == "open"
    assert ticket.assigned_manager_id is None
    assert ticket.assigned_to is None
    assert ticket.needs_triage is True
    assert "missing or inactive" in caplog.text


def test_non_manager_configured_user_is_not_assigned(monkeypatch):
    domain = SimpleNamespace(id=uuid.uuid4(), key="hr", name="HR", is_active=True)
    expert = SimpleNamespace(
        id=uuid.uuid4(), role=Role.HR.value, is_active=True
    )
    monkeypatch.setattr(
        ticket_assignment_service,
        "get_domain_managers",
        lambda db, domain_id: [expert],
    )
    ticket = _ticket()

    assigned = ticket_assignment_service.assign_ticket_to_domain_manager(
        FakeDatabase(domain), ticket, query_text="Annual leave policy"
    )

    assert assigned is None
    assert ticket.status == "open"
    assert ticket.assigned_manager_id is None


def test_low_confidence_ticket_creation_persists_manager_assignment(monkeypatch):
    domain = SimpleNamespace(id=uuid.uuid4(), key="hr", name="HR", is_active=True)
    manager = SimpleNamespace(
        id=uuid.uuid4(),
        role=Role.DOMAIN_MANAGER.value,
        is_active=True,
    )
    monkeypatch.setattr(
        ticket_assignment_service,
        "get_domain_managers",
        lambda db, domain_id: [manager],
    )
    monkeypatch.setattr(ticket_service, "is_ticketing_enabled", lambda db: True)
    monkeypatch.setattr(
        ticket_service, "_emit_ticket_created_signal", lambda **kwargs: None
    )
    db = FakeDatabase(domain=domain)

    ticket, _ = ticket_service.create_ticket_from_low_confidence(
        db=db,
        query_id="QRY_ASSIGN_INTEGRATION",
        user_id=str(uuid.uuid4()),
        original_question="How do I request annual leave?",
        generated_answer="Submit a request to your manager.",
        confidence_score=0.1,
        confidence_threshold=0.2,
        intent="fact",
        preserve_open_status=True,
    )

    assert ticket is db.added
    assert ticket.routed_domain_id == domain.id
    assert ticket.domain == "hr"
    assert ticket.assigned_manager_id == manager.id
    assert ticket.status == "open"
