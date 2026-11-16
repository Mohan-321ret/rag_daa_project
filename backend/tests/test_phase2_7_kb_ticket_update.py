"""
Phase 2.7: Knowledge Base Update Through Ticket Resolution — Integration Test Suite
-------------------------------------------------------------------------------------
Tests all 8 required criteria:
1. Valid PDF upload and processing
2. Valid DOCX upload and processing
3. Invalid file validation (unsupported extension & empty file)
4. Upload authorization (authorized Domain Manager vs unauthorized user/manager)
5. Successful ingestion (Status transition to COMPLETED, document metadata stored)
6. Failed ingestion (Status transition to FAILED when text extraction fails)
7. Vector database update (FAISS vector store contains embedded chunks)
8. Ticket-document association (Document linked to ticket in DB and relationship)
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
from app.models.ticket import Ticket, ticket_documents
from app.models.ticket_attachment import TicketAttachment, TicketAttachmentStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token
from app.services.vector_store import get_vector_store


def _create_user(role: Role, suffix: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{suffix}@phase27.test",
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
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id=owner_id,
        title=f"Phase 2.7 Test Ticket {ticket_id}",
        description="Ticket requiring knowledge base file attachment update",
        original_question="What is the refund process for international orders?",
        generated_answer="Unknown or low confidence answer.",
        confidence_score=0.25,
        confidence_threshold=0.50,
        priority="high",
        domain=domain,
        routed_domain_id=domain_id,
        assigned_manager_id=manager_id,
        assigned_to=str(manager_id) if manager_id else None,
        status=status,
    )


def _generate_docx_bytes(content: str) -> bytes:
    doc = DocxBuilder()
    doc.add_heading("Knowledge Base Document", 0)
    doc.add_paragraph(content)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _generate_simple_pdf_bytes(content: str) -> bytes:
    """Generates a minimal valid PDF with text stream content."""
    pdf_str = (
        "%PDF-1.4\n"
        "1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        "2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        "3 0 obj <</Type /Page /Parent 2 0 R /Resources <</Font <</F1 4 0 R>>>> /Contents 5 0 R>> endobj\n"
        "4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        f"5 0 obj <</Length {len(content) + 50}>> stream\n"
        "BT\n/F1 12 Tf\n100 700 Td\n(" + content.replace("(", "\\(").replace(")", "\\)") + ") Tj\nET\n"
        "endstream\nendobj\n"
        "xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n0000000111 00000 n \n0000000212 00000 n \n0000000283 00000 n \n"
        "trailer <</Size 6 /Root 1 0 R>>\nstartxref\n400\n%%EOF"
    )
    return pdf_str.encode("latin-1")


@pytest.fixture
def p27_test_env(monkeypatch):
    monkeypatch.setattr(settings, "watch_enabled", False)
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    owner_user = _create_user(Role.STANDARD_EMPLOYEE, f"owner-{suffix}")
    manager_user = _create_user(Role.DOMAIN_MANAGER, f"manager-{suffix}")
    unauth_manager = _create_user(Role.DOMAIN_MANAGER, f"unauth-{suffix}")

    domain = Domain(
        id=uuid.uuid4(),
        key=f"dom-{suffix}",
        name=f"Domain {suffix}",
        is_active=True,
    )
    other_domain = Domain(
        id=uuid.uuid4(),
        key=f"otherdom-{suffix}",
        name=f"Other Domain {suffix}",
        is_active=True,
    )

    tkt_id = f"TKT_P27_{suffix}"

    try:
        db.add_all([owner_user, manager_user, unauth_manager, domain, other_domain])
        db.flush()

        db.add(UserDomain(user_id=manager_user.id, domain_id=domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=domain.id, manager_user_id=manager_user.id, is_active=True))

        db.add(UserDomain(user_id=unauth_manager.id, domain_id=other_domain.id, is_primary=True))
        db.add(DomainRoutingConfig(domain_id=other_domain.id, manager_user_id=unauth_manager.id, is_active=True))

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
        owner_token = create_access_token(str(owner_user.id))
        unauth_token = create_access_token(str(unauth_manager.id))

        yield {
            "db": db,
            "owner": owner_user,
            "manager": manager_user,
            "unauth_manager": unauth_manager,
            "manager_token": manager_token,
            "owner_token": owner_token,
            "unauth_token": unauth_token,
            "ticket_id": tkt_id,
            "domain_id": domain.id,
        }
    finally:
        db.close()


def test_1_valid_pdf_upload(p27_test_env):
    """Test 1: Upload a valid PDF file for ticket knowledge base update."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]

    pdf_bytes = _generate_simple_pdf_bytes("International refund policy details and procedures.")

    files = {"file": ("refund_policy.pdf", pdf_bytes, "application/pdf")}
    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )

    assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
    data = response.json()

    assert data["ticket_id"] == ticket_id
    assert data["file_type"] == "PDF"
    assert data["original_filename"] == "refund_policy.pdf"
    assert data["status"] == TicketAttachmentStatus.COMPLETED.value
    assert data["document_id"] is not None


def test_2_valid_docx_upload(p27_test_env):
    """Test 2: Upload a valid DOCX file for ticket knowledge base update."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]

    docx_bytes = _generate_docx_bytes("Standard operating procedure for handling customer dispute tickets.")

    files = {"file": ("sop_disputes.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )

    assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
    data = response.json()

    assert data["ticket_id"] == ticket_id
    assert data["file_type"] == "DOCX"
    assert data["original_filename"] == "sop_disputes.docx"
    assert data["status"] == TicketAttachmentStatus.COMPLETED.value
    assert data["document_id"] is not None


def test_3_invalid_file_upload(p27_test_env):
    """Test 3: Invalid file uploads (unsupported extension and empty file) should be rejected."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]

    # 3a: Unsupported extension (.exe)
    exe_files = {"file": ("malicious.exe", b"MZ123456", "application/octet-stream")}
    res_exe = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=exe_files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res_exe.status_code == 415, f"Expected 415 Unsupported Media Type, got {res_exe.status_code}"

    # 3b: Empty file (0 bytes)
    empty_files = {"file": ("empty.txt", b"", "text/plain")}
    res_empty = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=empty_files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert res_empty.status_code in (400, 413, 422), f"Expected 400/413/422 for empty file, got {res_empty.status_code}"


def test_4_upload_authorization(p27_test_env):
    """Test 4: Authorization check - Standard employees and managers from another domain cannot upload."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]

    txt_files = {"file": ("kb_notes.txt", b"Valid text content for auth test.", "text/plain")}

    # Standard employee attempt
    res_owner = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=txt_files,
        headers={"Authorization": f"Bearer {env['owner_token']}"},
    )
    assert res_owner.status_code in (403, 404), f"Expected 403/404 for standard employee, got {res_owner.status_code}"

    # Unauthorized Manager (manager of a different domain)
    res_unauth = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=txt_files,
        headers={"Authorization": f"Bearer {env['unauth_token']}"},
    )
    assert res_unauth.status_code in (403, 404), f"Expected 403/404 for unauth domain manager, got {res_unauth.status_code}"


def test_5_successful_ingestion(p27_test_env):
    """Test 5: Successful ingestion creates Document, updates status to COMPLETED and sets metadata."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]
    db = env["db"]

    text_content = (
        "Phase 2.7 Knowledge Base Ingestion Policy Document.\n"
        "Section 1: All claims under $500 are eligible for automatic reimbursement within 5 business days."
    )
    files = {"file": ("policy_reimbursement.txt", text_content.encode("utf-8"), "text/plain")}

    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert response.status_code == 202
    data = response.json()

    attachment_id = data["attachment_id"]
    doc_id = data["document_id"]

    assert data["status"] == TicketAttachmentStatus.COMPLETED.value
    assert doc_id is not None

    # Verify Database records
    db.expire_all()
    attachment = db.query(TicketAttachment).filter(TicketAttachment.attachment_id == attachment_id).first()
    assert attachment is not None
    assert attachment.status == TicketAttachmentStatus.COMPLETED.value
    assert attachment.document_id == doc_id

    doc = db.query(Document).filter(Document.document_id == doc_id).first()
    assert doc is not None
    assert doc.processing_status == "indexed"
    assert "reimbursement" in doc.extracted_text.lower()


def test_6_failed_ingestion(p27_test_env):
    """Test 6: Failed ingestion marks attachment status as FAILED and captures error message."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]
    db = env["db"]

    # Upload a text file with only non-text / whitespace content which fails text cleaner check
    files = {"file": ("corrupt_sample.txt", b"\x00\x00\x00\x00\x00", "text/plain")}

    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )

    assert response.status_code == 202
    data = response.json()

    assert data["status"] == TicketAttachmentStatus.FAILED.value
    assert data["error_message"] is not None

    db.expire_all()
    attachment = db.query(TicketAttachment).filter(TicketAttachment.attachment_id == data["attachment_id"]).first()
    assert attachment is not None
    assert attachment.status == TicketAttachmentStatus.FAILED.value


def test_7_vector_database_update(p27_test_env):
    """Test 7: Verification that chunk embeddings are stored in FAISS vector database during ingestion."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]

    unique_keyword = f"UNIQUE_VECTOR_KEYWORD_{uuid.uuid4().hex[:8].upper()}"
    policy_text = (
        f"Special resolution procedure for customer escalation {unique_keyword}.\n"
        "Customers with VIP status receive immediate replacement within 24 hours of ticket filing."
    )

    files = {"file": ("vip_escalation.txt", policy_text.encode("utf-8"), "text/plain")}
    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == TicketAttachmentStatus.COMPLETED.value

    # Perform vector database search
    vector_store = get_vector_store()
    results = vector_store.search("Special resolution procedure for customer escalation VIP status", top_k=20)

    assert len(results) > 0, "Expected at least 1 vector match from FAISS"
    all_texts = [r["text"] for r in results] + [entry.get("text", "") for entry in vector_store._id_map.values()]
    assert any(unique_keyword in text for text in all_texts if text), f"Vector store should contain {unique_keyword}"


def test_8_ticket_document_association(p27_test_env):
    """Test 8: Uploaded KB document is linked to ticket.documents and ticket supporting_document_ids."""
    client = TestClient(app)
    env = p27_test_env
    ticket_id = env["ticket_id"]
    db = env["db"]

    files = {"file": ("linked_kb_policy.txt", b"Policy details linking to support ticket.", "text/plain")}
    response = client.post(
        f"/api/v1/tickets/{ticket_id}/upload-kb?sync=true",
        files=files,
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert response.status_code == 202
    data = response.json()
    doc_id = data["document_id"]
    assert doc_id is not None

    db.expire_all()
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    assert ticket is not None

    # Check relationship association
    doc_ids_in_ticket = [d.document_id for d in ticket.documents]
    assert doc_id in doc_ids_in_ticket, f"Document {doc_id} should be associated with ticket.documents"

    # Check supporting_document_ids column
    assert doc_id in (ticket.supporting_document_ids or ""), f"Document {doc_id} should be in supporting_document_ids"

    # Check list attachments endpoint
    list_res = client.get(
        f"/api/v1/tickets/{ticket_id}/attachments",
        headers={"Authorization": f"Bearer {env['manager_token']}"},
    )
    assert list_res.status_code == 200
    attachments_list = list_res.json()
    assert len(attachments_list) >= 1
    assert any(a["document_id"] == doc_id for a in attachments_list)
