"""
Phase 2.8: File-Based Ticket Resolution — Integration Test Suite
------------------------------------------------------------------
Tests strict resolution gating and status handling for file-based ticket resolution:
1. File-only resolution (resolution_type = FILE when document is indexed)
2. File + Text explanation resolution (resolution_type = BOTH)
3. Rejection when document processing is PENDING or PROCESSING (ticket stays open/in_progress)
4. Rejection when document processing is FAILED (ticket stays open/in_progress for retry)
5. Successful retry flow after correcting/re-uploading document
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
        email=f"{role.value}-{suffix}@phase28.test",
        full_name=f"User {role.value} {suffix}",
        hashed_password="test-password-hash",
        role=role.value,
        is_active=True,
    )


def _create_ticket(
    ticket_id: str,
    owner_id: uuid.UUID,
    *,
    domain: str = "Finance",
    domain_id: uuid.UUID = None,
    manager_id: uuid.UUID = None,
    status: str = "open",
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id=owner_id,
        title=f"Phase 2.8 Test Ticket {ticket_id}",
        description="Ticket requiring file-based resolution testing",
        original_question="How do I claim tax deductions on travel expenses?",
        generated_answer="Low confidence answer.",
        confidence_score=0.30,
        confidence_threshold=0.50,
        priority="medium",
        domain=domain,
        routed_domain_id=domain_id,
        assigned_manager_id=manager_id,
        assigned_to=str(manager_id) if manager_id else None,
        status=status,
    )


def _generate_docx_bytes(content: str) -> bytes:
    doc = DocxBuilder()
    doc.add_heading("Travel Expense Guidelines", 0)
    doc.add_paragraph(content)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def p28_test_env(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    owner_user = _create_user(Role.STANDARD_EMPLOYEE, f"owner-{suffix}")
    manager_user = _create_user(Role.DOMAIN_MANAGER, f"manager-{suffix}")

    domain = Domain(
        id=uuid.uuid4(),
        key=f"dom-p28-{suffix}",
        name=f"Finance {suffix}",
        is_active=True,
    )

    tkt_id = f"TKT_P28_{suffix}"

    try:
        db.add_all([owner_user, manager_user, domain])
        db.flush()

        db.add(UserDomain(user_id=manager_user.id, domain_id=domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=domain.id, manager_user_id=manager_user.id, is_active=True))

        tkt = _create_ticket(
            tkt_id,
            owner_user.id,
            domain=domain.name,
            domain_id=domain.id,
            manager_id=manager_user.id,
            status="open",
        )
        db.add(tkt)
        db.commit()

        manager_token = create_access_token(str(manager_user.id))

        yield {
            "db": db,
            "owner": owner_user,
            "manager": manager_user,
            "manager_token": manager_token,
            "ticket_id": tkt_id,
            "domain_id": domain.id,
            "suffix": suffix,
        }
    finally:
        db.close()


def test_1_file_only_ticket_resolution(p28_test_env):
    """
    Test 1: Resolve ticket using KB file only (resolution_type = FILE).
    Document uploads, processes successfully, and resolving marks ticket RESOLVED.
    """
    client = TestClient(app)
    env = p28_test_env
    ticket_id = env["ticket_id"]
    headers = {"Authorization": f"Bearer {env['manager_token']}"}

    docx_bytes = _generate_docx_bytes("Employees may claim travel expenses up to $500 per trip with receipts.")

    # 1. Upload KB file to ticket
    upload_res = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        headers=headers,
        files={"file": ("Travel_Policy.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert upload_res.status_code == 202, upload_res.text
    attachment_data = upload_res.json()
    assert attachment_data["status"] == "COMPLETED"
    attachment_id = attachment_data["attachment_id"]

    # 2. Resolve ticket with resolution_type = FILE (no manual resolution text)
    resolve_res = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        headers=headers,
        json={
            "resolution_type": "FILE",
            "attachment_id": attachment_id,
            "internal_notes": "Resolved via travel policy document upload.",
        },
    )
    assert resolve_res.status_code == 200, resolve_res.text
    tkt_data = resolve_res.json()
    assert tkt_data["status"] == "resolved"
    assert tkt_data["resolution_type"] == "FILE"
    assert tkt_data["resolution_format"] == "FILE"
    assert "Travel_Policy.docx" in tkt_data["resolution"]
    assert tkt_data["resolved_at"] is not None


def test_2_file_and_text_ticket_resolution(p28_test_env):
    """
    Test 2: Resolve ticket using BOTH explanation text and uploaded KB file (resolution_type = BOTH).
    """
    client = TestClient(app)
    env = p28_test_env
    db = env["db"]
    ticket_id = env["ticket_id"]
    headers = {"Authorization": f"Bearer {env['manager_token']}"}

    # Reset ticket status to open
    tkt = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    tkt.status = "open"
    db.commit()

    docx_bytes = _generate_docx_bytes("Updated travel claim policy 2026.")

    # Upload attachment
    upload_res = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        headers=headers,
        files={"file": ("Policy_2026.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert upload_res.status_code == 202, upload_res.text
    attachment_id = upload_res.json()["attachment_id"]

    # Resolve with both text and attachment
    explanation = "Please follow the 2026 updated expense report guidelines in the attached document."
    resolve_res = client.post(
        f"/api/v1/tickets/{ticket_id}/resolve",
        headers=headers,
        json={
            "resolution": explanation,
            "resolution_type": "BOTH",
            "attachment_id": attachment_id,
        },
    )
    assert resolve_res.status_code == 200, resolve_res.text
    tkt_data = resolve_res.json()
    assert tkt_data["status"] == "resolved"
    assert tkt_data["resolution_type"] == "BOTH"
    assert tkt_data["resolution_format"] == "BOTH"
    assert tkt_data["resolution"] == explanation


def test_3_gating_pending_or_processing_document(p28_test_env):
    """
    Test 3: Attempting to resolve ticket when attachment is in PROCESSING state should fail.
    Ticket MUST NOT be marked resolved.
    """
    client = TestClient(app)
    env = p28_test_env
    db = env["db"]
    headers = {"Authorization": f"Bearer {env['manager_token']}"}
    suffix = env["suffix"]

    # Create dummy ticket and attachment in PROCESSING status
    tkt_proc_id = f"TKT_P28_PROC_{suffix}"
    tkt_proc = _create_ticket(
        ticket_id=tkt_proc_id,
        owner_id=env["owner"].id,
        domain="Finance",
        domain_id=env["domain_id"],
        manager_id=env["manager"].id,
        status="open",
    )
    db.add(tkt_proc)
    db.flush()

    attachment_proc = TicketAttachment(
        attachment_id=f"ATT_PROC_{suffix[:10]}",
        ticket_id=tkt_proc_id,
        uploaded_by_id=env["manager"].id,
        original_filename="ProcessingDoc.pdf",
        file_type="PDF",
        file_size=12345,
        status=TicketAttachmentStatus.PROCESSING.value,
    )
    db.add(attachment_proc)
    db.commit()

    # Attempt resolution
    res = client.post(
        f"/api/v1/tickets/{tkt_proc_id}/resolve",
        headers=headers,
        json={
            "resolution_type": "FILE",
            "attachment_id": attachment_proc.attachment_id,
        },
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "processing is in progress" in detail or "in progress" in detail

    # Verify ticket state in DB remains open
    db.refresh(tkt_proc)
    assert tkt_proc.status == "open"


def test_4_gating_failed_document_and_retry_flow(p28_test_env):
    """
    Test 4 & 5: Attempting to resolve with a FAILED document fails and shows processing failure.
    Ticket remains open. Manager can then re-upload a valid document and resolve successfully.
    """
    client = TestClient(app)
    env = p28_test_env
    db = env["db"]
    headers = {"Authorization": f"Bearer {env['manager_token']}"}
    suffix = env["suffix"]

    # Create ticket and attachment in FAILED status
    tkt_failed_id = f"TKT_P28_FAIL_{suffix}"
    tkt_failed = _create_ticket(
        ticket_id=tkt_failed_id,
        owner_id=env["owner"].id,
        domain="Finance",
        domain_id=env["domain_id"],
        manager_id=env["manager"].id,
        status="open",
    )
    db.add(tkt_failed)
    db.flush()

    failed_att = TicketAttachment(
        attachment_id=f"ATT_FAIL_{suffix[:10]}",
        ticket_id=tkt_failed_id,
        uploaded_by_id=env["manager"].id,
        original_filename="CorruptDoc.pdf",
        file_type="PDF",
        file_size=999,
        status=TicketAttachmentStatus.FAILED.value,
        error_message="Corrupted PDF header stream.",
    )
    db.add(failed_att)
    db.commit()

    # Attempt resolution with failed document -> Expect 400 with error details
    res = client.post(
        f"/api/v1/tickets/{tkt_failed_id}/resolve",
        headers=headers,
        json={
            "resolution_type": "FILE",
            "attachment_id": failed_att.attachment_id,
        },
    )
    assert res.status_code == 400
    assert "Document processing failed" in res.json()["detail"]
    assert "Corrupted PDF header stream" in res.json()["detail"]

    # Verify ticket status unchanged
    db.refresh(tkt_failed)
    assert tkt_failed.status == "open"

    # Retry flow: Upload valid replacement file
    valid_bytes = _generate_docx_bytes("Correct expense policy details.")
    upload_res = client.post(
        f"/api/v1/tickets/{tkt_failed_id}/upload-kb?sync=true",
        headers=headers,
        files={"file": ("ValidPolicy.docx", valid_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert upload_res.status_code == 202, upload_res.text
    valid_att_id = upload_res.json()["attachment_id"]

    # Resolve with the new valid attachment
    resolve_res = client.post(
        f"/api/v1/tickets/{tkt_failed_id}/resolve",
        headers=headers,
        json={
            "resolution_type": "FILE",
            "attachment_id": valid_att_id,
        },
    )
    assert resolve_res.status_code == 200, resolve_res.text
    assert resolve_res.json()["status"] == "resolved"
