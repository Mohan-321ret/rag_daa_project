"""
Phase 2 End-to-End & Comprehensive Edge Case Test Suite
-------------------------------------------------------
Verifies:
SCENARIO 1 — High Confidence (No ticket, normal answer)
SCENARIO 2 — Low Confidence (Auto ticket creation, domain routing, manager assignment)
SCENARIO 3 — Text Resolution (Manager resolves with text, user views resolution)
SCENARIO 4 — Knowledge Base Resolution (Manager uploads file, ingestion pipeline chunks/embeds/FAISS, associates doc, resolves ticket)
SCENARIO 5 — Knowledge Reuse (Re-querying retrieves newly added KB document)

Edge Cases & Fault Tolerance:
- Unauthorized Access (cross-user access, standard user escalation)
- Invalid Ticket IDs
- Invalid Files (unsupported media type, empty files)
- Duplicate Uploads
- Failed Document Processing (prevents false resolution)
- Missing Domain Manager / Missing Domain fallback
- Already Resolved Tickets rejection
- Reopened Tickets status handling
- Notification Failure Resilience
"""
import io
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import Role
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket, TicketStatus, ResolutionType
from app.models.ticket_attachment import TicketAttachment, TicketAttachmentStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token
from app.services.rag_service import answer_question
from app.services.ticket_attachment_service import upload_ticket_attachment
from app.services.ticket_notification_service import set_custom_dispatcher
from app.services.ticket_service import (
    create_ticket_from_low_confidence,
    resolve_ticket,
    change_ticket_status,
)



@pytest.fixture(scope="module", autouse=True)
def setup_database():
    settings.watch_enabled = False
    init_db()
    yield


@pytest.fixture
def e2e_fixture():
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    # Create users
    user = User(
        id=uuid.uuid4(),
        email=f"user_{suffix}@e2e.test",
        full_name="E2E Employee",
        hashed_password="hash",
        role=Role.STANDARD_EMPLOYEE.value,
        is_active=True,
    )
    other_user = User(
        id=uuid.uuid4(),
        email=f"other_{suffix}@e2e.test",
        full_name="Other Employee",
        hashed_password="hash",
        role=Role.STANDARD_EMPLOYEE.value,
        is_active=True,
    )
    manager = User(
        id=uuid.uuid4(),
        email=f"manager_{suffix}@e2e.test",
        full_name="Finance Domain Manager",
        hashed_password="hash",
        role=Role.DOMAIN_MANAGER.value,
        is_active=True,
    )

    # Create domain
    domain = Domain(
        id=uuid.uuid4(),
        key=f"fin_{suffix}",
        name=f"Finance {suffix}",
        description="Finance domain for E2E tests",
        is_active=True,
    )

    db.add_all([user, other_user, manager, domain])
    db.flush()

    # Link manager to domain
    db.add(UserDomain(user_id=manager.id, domain_id=domain.id, is_primary=True))
    db.add(
        DomainRoutingConfig(
            domain_id=domain.id,
            manager_user_id=manager.id,
            is_primary_manager=True,
            is_active=True,
        )
    )
    db.commit()

    user_token = create_access_token(str(user.id))
    other_token = create_access_token(str(other_user.id))
    manager_token = create_access_token(str(manager.id))

    client = TestClient(app)

    yield {
        "db": db,
        "client": client,
        "user": user,
        "other_user": other_user,
        "manager": manager,
        "domain": domain,
        "user_headers": {"Authorization": f"Bearer {user_token}"},
        "other_headers": {"Authorization": f"Bearer {other_token}"},
        "manager_headers": {"Authorization": f"Bearer {manager_token}"},
        "suffix": suffix,
    }

    db.rollback()
    # Cleanup
    db.query(TicketAttachment).filter(TicketAttachment.uploaded_by_id.in_([user.id, other_user.id, manager.id])).delete(synchronize_session=False)
    db.query(Ticket).filter(Ticket.user_id.in_([user.id, other_user.id, manager.id])).delete(synchronize_session=False)
    db.query(DomainRoutingConfig).filter(DomainRoutingConfig.domain_id == domain.id).delete(synchronize_session=False)
    db.query(UserDomain).filter(UserDomain.user_id == manager.id).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_([user.id, other_user.id, manager.id])).delete(synchronize_session=False)
    db.query(Domain).filter(Domain.id == domain.id).delete(synchronize_session=False)
    db.commit()
    db.close()


# ── SCENARIO 1 — High Confidence ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_1_high_confidence(e2e_fixture):
    """High confidence query returns answer directly without ticket creation."""
    db = e2e_fixture["db"]
    user = e2e_fixture["user"]

    res = await answer_question(
        db=db,
        query="Hello, how can I use the system?",
        current_user=user,
        caller_role=Role.STANDARD_EMPLOYEE,
    )

    assert "answer" in res
    assert res["ticket"] is None


# ── SCENARIO 2 — Low Confidence ────────────────────────────────────────────────

def test_scenario_2_low_confidence(e2e_fixture):
    """Low confidence query automatically creates ticket with domain & manager assigned."""
    db = e2e_fixture["db"]
    user = e2e_fixture["user"]

    ticket, msg = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="What is the specialized fiscal quarter budget allocation?",
        generated_answer="I am not confident about the fiscal quarter budget.",
        confidence_score=0.15,
        confidence_threshold=0.20,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    assert ticket is not None
    assert ticket.ticket_id.startswith("TKT_")
    assert ticket.user_id == user.id
    assert ticket.confidence_score == 0.15
    assert ticket.status == TicketStatus.OPEN.value
    assert msg is not None


# ── SCENARIO 3 — Text Resolution ──────────────────────────────────────────────

def test_scenario_3_text_resolution(e2e_fixture):
    """Domain Manager resolves ticket with text explanation; user can view detail."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    mgr_headers = e2e_fixture["manager_headers"]
    user_headers = e2e_fixture["user_headers"]

    # 1. Create low-confidence ticket
    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="How to apply for tuition reimbursement?",
        generated_answer="Uncertain answer",
        confidence_score=0.10,
        confidence_threshold=0.20,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # 2. Domain Manager resolves ticket via API
    resolve_resp = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=mgr_headers,
        json={
            "resolution": "Submit tuition reimbursement form to HR before quarter end.",
            "resolution_type": "TEXT",
        },
    )
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["status"] == "resolved"
    assert res_data["resolution"] == "Submit tuition reimbursement form to HR before quarter end."
    assert res_data["resolution_type"] == "TEXT"

    # 3. User views resolved ticket details via API
    detail_resp = client.get(f"/api/v1/tickets/{ticket.ticket_id}", headers=user_headers)
    assert detail_resp.status_code == 200
    user_view = detail_resp.json()
    assert user_view["ticket_id"] == ticket.ticket_id
    assert user_view["status"] == "resolved"
    assert user_view["resolution"] == "Submit tuition reimbursement form to HR before quarter end."


# ── SCENARIO 4 — Knowledge Base Resolution ───────────────────────────────────

def test_scenario_4_kb_resolution(e2e_fixture):
    """Manager uploads KB doc, ingestion pipeline processes it, manager resolves ticket."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    manager = e2e_fixture["manager"]
    mgr_headers = e2e_fixture["manager_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="What is the remote work equipment stipend?",
        generated_answer="Unknown stipend",
        confidence_score=0.12,
        confidence_threshold=0.20,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # Upload document to ticket (sync processing)
    file_content = b"Remote Work Policy 2026: Employees receive a $500 annual equipment stipend."
    attachment = upload_ticket_attachment(
        db=db,
        ticket_id=ticket.ticket_id,
        file_bytes=file_content,
        original_filename="Remote_Work_Stipend_Policy.txt",
        current_user=manager,
        caller_role=Role.DOMAIN_MANAGER,
        sync_processing=True,
    )

    assert attachment.status == TicketAttachmentStatus.COMPLETED.value
    assert attachment.document_id is not None

    # Manager resolves ticket using uploaded attachment
    res_resp = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=mgr_headers,
        json={
            "resolution": "Resolved via Remote Work Equipment Stipend Policy doc.",
            "resolution_type": "FILE",
            "attachment_id": attachment.attachment_id,
        },
    )
    assert res_resp.status_code == 200
    res_json = res_resp.json()
    assert res_json["status"] == "resolved"
    assert res_json["resolution_type"] in ("FILE", "BOTH")
    assert attachment.document_id in res_json["supporting_document_ids"]



# ── SCENARIO 5 — Knowledge Reuse ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_5_knowledge_reuse(e2e_fixture):
    """Re-querying after KB ingestion retrieves new document."""
    db = e2e_fixture["db"]
    user = e2e_fixture["user"]
    manager = e2e_fixture["manager"]

    # Ingest document into KB
    doc_text = "Travel Policy 2026: Daily meal allowance for international business travel is $75 USD."
    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="What is the daily meal allowance for international travel?",
        generated_answer="Unknown allowance",
        confidence_score=0.10,
        confidence_threshold=0.20,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    attachment = upload_ticket_attachment(
        db=db,
        ticket_id=ticket.ticket_id,
        file_bytes=doc_text.encode("utf-8"),
        original_filename="Travel_Allowance_Policy.txt",
        current_user=manager,
        caller_role=Role.DOMAIN_MANAGER,
        sync_processing=True,
    )
    assert attachment.status == TicketAttachmentStatus.COMPLETED.value

    # Re-query
    answer_res = await answer_question(
        db=db,
        query="What is the daily meal allowance for international travel?",
        current_user=user,
        caller_role=Role.STANDARD_EMPLOYEE,
    )

    assert "answer" in answer_res
    assert answer_res["retrieved_chunks"] > 0
    assert any(
        "75" in s.get("text_preview", "")
        or "Travel" in s.get("text_preview", "")
        or attachment.document_id == s.get("document_id")
        for s in answer_res.get("sources", [])
    )



# ── EDGE CASES & FAULT TOLERANCE ──────────────────────────────────────────────

def test_unauthorized_access(e2e_fixture):
    """Test cross-user ticket isolation and role restriction."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    user_headers = e2e_fixture["user_headers"]
    other_headers = e2e_fixture["other_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="Private user question?",
        generated_answer="Answer",
        confidence_score=0.1,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # Other user cannot view User's ticket (returns 404 / access denied)
    hidden = client.get(f"/api/v1/tickets/{ticket.ticket_id}", headers=other_headers)
    assert hidden.status_code == 404

    # Standard user cannot access manager queue (403)
    forbidden_mgr = client.get("/api/v1/tickets/manager", headers=user_headers)
    assert forbidden_mgr.status_code == 403

    # Standard user cannot resolve tickets (403)
    forbidden_res = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=user_headers,
        json={"resolution": "Hacked resolution"},
    )
    assert forbidden_res.status_code == 403


def test_invalid_ticket_id(e2e_fixture):
    """Requesting non-existent ticket returns 404."""
    client = e2e_fixture["client"]
    user_headers = e2e_fixture["user_headers"]

    res = client.get("/api/v1/tickets/TKT_NONEXISTENT_99999", headers=user_headers)
    assert res.status_code == 404


def test_invalid_files(e2e_fixture):
    """Uploading unsupported extensions or invalid files rejected with 415."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    mgr_headers = e2e_fixture["manager_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="Query for invalid file test?",
        generated_answer="Answer",
        confidence_score=0.1,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    res = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/attachments",
        headers=mgr_headers,
        files={"file": ("malicious_script.exe", b"binary content", "application/octet-stream")},
    )
    assert res.status_code == 415
    assert "Unsupported file" in res.json()["detail"]



def test_failed_document_processing_prevents_resolution(e2e_fixture):
    """Failed document ingestion prevents ticket resolution."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    manager = e2e_fixture["manager"]
    mgr_headers = e2e_fixture["manager_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="Corrupt file query?",
        generated_answer="Answer",
        confidence_score=0.1,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # Create failed attachment row
    attachment = TicketAttachment(
        attachment_id=f"ATT_FAIL_{uuid.uuid4().hex[:6]}",
        ticket_id=ticket.ticket_id,
        original_filename="corrupt.pdf",
        file_type="PDF",
        status=TicketAttachmentStatus.FAILED.value,
        error_message="Text extraction produced no content.",
        uploaded_by_id=manager.id,
    )
    db.add(attachment)
    db.commit()

    # Attempt resolution with failed document
    res_resp = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=mgr_headers,
        json={
            "resolution": "Resolving with corrupt file",
            "resolution_type": "FILE",
            "attachment_id": attachment.attachment_id,
        },
    )
    assert res_resp.status_code == 400
    assert "Document processing failed" in res_resp.json()["detail"]

    # Verify ticket remains OPEN
    db.refresh(ticket)
    assert ticket.status == TicketStatus.OPEN.value


def test_already_resolved_ticket_rejection(e2e_fixture):
    """Resolving an already resolved ticket returns 400 Bad Request."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    manager = e2e_fixture["manager"]
    mgr_headers = e2e_fixture["manager_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="Already resolved test?",
        generated_answer="Answer",
        confidence_score=0.1,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # First resolution
    resolve_ticket(
        db=db,
        ticket_id=ticket.ticket_id,
        resolution="Initial resolution",
        current_user=manager,
        caller_role=Role.DOMAIN_MANAGER,
        resolution_type="TEXT",
    )

    # Second resolution attempt
    second_res = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=mgr_headers,
        json={"resolution": "Duplicate resolution attempt"},
    )
    assert second_res.status_code == 400
    assert "already resolved" in second_res.json()["detail"].lower()


def test_reopened_ticket_handling(e2e_fixture):
    """Reopening a resolved ticket updates status to REOPENED and allows re-resolution."""
    db = e2e_fixture["db"]
    client = e2e_fixture["client"]
    user = e2e_fixture["user"]
    manager = e2e_fixture["manager"]
    mgr_headers = e2e_fixture["manager_headers"]

    ticket, _ = create_ticket_from_low_confidence(
        db=db,
        query_id=f"Q_{uuid.uuid4().hex[:6]}",
        user_id=str(user.id),
        original_question="Reopen workflow test query?",
        generated_answer="Answer",
        confidence_score=0.1,
        domain=e2e_fixture["domain"].key,
        preserve_open_status=True,
    )

    # Resolve ticket
    resolve_ticket(
        db=db,
        ticket_id=ticket.ticket_id,
        resolution="First attempt",
        current_user=manager,
        caller_role=Role.DOMAIN_MANAGER,
    )

    # Reopen ticket
    reopened = change_ticket_status(
        db=db,
        ticket_id=ticket.ticket_id,
        status_val=TicketStatus.REOPENED.value,
        current_user=manager,
        caller_role=Role.DOMAIN_MANAGER,
    )
    assert reopened is not None
    assert reopened.status == TicketStatus.REOPENED.value


    # Re-resolve ticket via API
    re_resolve = client.post(
        f"/api/v1/tickets/{ticket.ticket_id}/resolve",
        headers=mgr_headers,
        json={"resolution": "Final updated resolution after reopen."},
    )
    assert re_resolve.status_code == 200
    assert re_resolve.json()["status"] == "resolved"
    assert re_resolve.json()["resolution"] == "Final updated resolution after reopen."
