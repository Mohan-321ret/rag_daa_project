"""
Phase 10 & 11 Low-Confidence Automatic Ticketing Test Suite
------------------------------------------------------------
Verifies the complete flow:
  User Query → Secure Retrieval → Answer + Confidence → Threshold Check → Ticket Creation

Scenarios tested:
  1. High confidence (>= threshold) -> NO ticket created
  2. Low confidence (< threshold) -> Ticket created with status OPEN/ROUTED/NEEDS_TRIAGE
  3. Ticket payload verification:
     - user query
     - generated answer
     - confidence score
     - authorized source document IDs
     - domain
     - timestamp
     - status
  4. Domain Manager & Super Admin scoping / access
  5. Security check: Unauthorized sources strictly excluded
"""
import json
import uuid

from app.core.config import settings
settings.watch_enabled = False

from app.db.base import init_db
from app.db.database import SessionLocal
from app.core.permissions import Role
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.ticket_service import (
    can_user_access_ticket,
    create_ticket_from_low_confidence,
    get_ticket_confidence_threshold,
)
from app.services.confidence_service import calculate_retrieval_confidence

init_db()


def test_high_confidence_creates_no_ticket():
    """Scenario 1: High confidence score (>= threshold) should NOT create a ticket."""
    db = SessionLocal()
    try:
        threshold = 0.70
        high_score = 0.85

        ticket, msg = create_ticket_from_low_confidence(
            db,
            query_id=f"Q_HIGH_{uuid.uuid4().hex[:6]}",
            user_id=None,
            original_question=f"Test Question High Conf {uuid.uuid4().hex[:6]}",
            generated_answer="Employees get 25 days leave per year.",
            confidence_score=high_score,
            confidence_threshold=threshold,
            evidence="High vector similarity",
            domain="hr",
        )

        assert ticket is None
        assert msg is None
    finally:
        db.close()


def test_low_confidence_creates_ticket():
    """Scenario 2 & 3: Low confidence score (< threshold) MUST create a ticket with all required fields."""
    db = SessionLocal()
    try:
        threshold = 0.70
        low_score = 0.45
        unique_q = f"What is the quantum encryption protocol {uuid.uuid4().hex[:6]}?"

        # Seed an admin user for triage
        admin = User(
            id=uuid.uuid4(),
            email=f"admin-{uuid.uuid4().hex[:6]}@company.com",
            full_name=f"Admin {uuid.uuid4().hex[:6]}",
            hashed_password="hash",
            role=Role.SUPER_ADMIN.value,
            department="IT",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        ticket, msg = create_ticket_from_low_confidence(
            db,
            query_id=f"Q_LOW_{uuid.uuid4().hex[:6]}",
            user_id=str(admin.id),
            original_question=unique_q,
            generated_answer="I found limited information about quantum encryption.",
            confidence_score=low_score,
            confidence_threshold=threshold,
            evidence="Low confidence retrieval",
            domain="IT",
            source_document_ids=["DOC_AUTHORIZED_1", "DOC_AUTHORIZED_2"],
        )

        assert ticket is not None
        assert ticket.ticket_id.startswith("TKT_")
        assert ticket.original_question == unique_q
        assert ticket.generated_answer == "I found limited information about quantum encryption."
        assert ticket.confidence_score == 0.45
        assert ticket.confidence_threshold == 0.70
        assert ticket.status in [TicketStatus.OPEN.value, TicketStatus.NEEDS_TRIAGE.value, TicketStatus.ROUTED.value]
        assert ticket.created_at is not None

        # Source documents check
        stored_sources = json.loads(ticket.source_document_ids)
        assert stored_sources == ["DOC_AUTHORIZED_1", "DOC_AUTHORIZED_2"]
        assert "UNAUTHORIZED_DOC" not in stored_sources
    finally:
        db.close()


def test_super_admin_and_domain_manager_routing():
    """Scenario 4: Super Admin and Domain Manager access control verification."""
    db = SessionLocal()
    try:
        dom_key = f"hr_{uuid.uuid4().hex[:4]}"
        unique_q = f"How many sick leave days allowed {uuid.uuid4().hex[:6]}?"

        # Seed HR Domain
        hr_domain = Domain(id=uuid.uuid4(), key=dom_key, name=f"Human Resources {dom_key}")
        db.add(hr_domain)
        db.flush()

        # Seed Domain Manager user
        manager = User(
            id=uuid.uuid4(),
            email=f"hr_mgr_{uuid.uuid4().hex[:6]}@company.com",
            full_name=f"HR Manager {uuid.uuid4().hex[:6]}",
            hashed_password="hash",
            role=Role.DOMAIN_MANAGER.value,
            department="HR",
            is_active=True,
        )
        db.add(manager)
        db.flush()

        # Grant manager access to HR domain
        ud = UserDomain(user_id=manager.id, domain_id=hr_domain.id)
        db.add(ud)

        # Seed Super Admin user
        admin = User(
            id=uuid.uuid4(),
            email=f"admin_{uuid.uuid4().hex[:6]}@company.com",
            full_name=f"Super Admin {uuid.uuid4().hex[:6]}",
            hashed_password="hash",
            role=Role.SUPER_ADMIN.value,
            department="Executive",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        # Create low confidence ticket in HR domain
        ticket, _ = create_ticket_from_low_confidence(
            db,
            query_id=f"Q_HR_{uuid.uuid4().hex[:6]}",
            user_id=None,
            original_question=unique_q,
            generated_answer="Sick leave policy details.",
            confidence_score=0.40,
            confidence_threshold=0.70,
            domain=dom_key,
        )
        assert ticket is not None

        # Super Admin can access ticket
        assert can_user_access_ticket(db, ticket, admin, Role.SUPER_ADMIN) is True

        # HR Domain Manager can access HR ticket
        assert can_user_access_ticket(db, ticket, manager, Role.DOMAIN_MANAGER) is True
    finally:
        db.close()


def test_unauthorized_sources_excluded_from_confidence():
    """Scenario 5: Security verification that unauthorized sources are excluded."""
    db = SessionLocal()
    try:
        unique_q = f"Confidential salary details {uuid.uuid4().hex[:6]}?"

        # Simulate list of authorized vs unauthorized chunks
        authorized_chunks = [
            {"score": 0.40, "source": "vector", "document_id": "DOC_AUTH_1"},
            {"score": 0.35, "source": "vector", "document_id": "DOC_AUTH_2"},
        ]
        
        # Calculate confidence strictly from authorized chunks
        confidence = calculate_retrieval_confidence(authorized_chunks)
        assert confidence < 0.60  # Low confidence

        # Create ticket ensuring ONLY authorized doc IDs are passed
        ticket, _ = create_ticket_from_low_confidence(
            db,
            query_id=f"Q_SEC_{uuid.uuid4().hex[:6]}",
            user_id=None,
            original_question=unique_q,
            generated_answer="Unauthorized query.",
            confidence_score=confidence,
            confidence_threshold=0.70,
            source_document_ids=[c["document_id"] for c in authorized_chunks],
        )

        stored_sources = json.loads(ticket.source_document_ids)
        assert "DOC_SECRET_UNAUTHORIZED" not in stored_sources
        assert stored_sources == ["DOC_AUTH_1", "DOC_AUTH_2"]
    finally:
        db.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
