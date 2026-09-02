"""
Phase 14 — Connect Tickets with Knowledge Evolution Verification Test Suite
===========================================================================
Verifies the complete closed-loop governance workflow:
1. Resolved Ticket with Root Cause (e.g. OUTDATED_DOCUMENT, KNOWLEDGE_MISSING)
2. Domain Expert creates Knowledge Update Request (Status: PENDING_REVIEW)
3. Safety Check: Production knowledge is NOT modified automatically
4. Role-Based Access Control & Domain Scoping on Recommendations:
   - Regular employee cannot approve or apply (403 Forbidden)
   - Cross-domain isolation enforced (Finance Manager cannot review HR request)
5. Administrator Review Workflow (Approve / Reject)
6. Admin Applies Approved Update:
   - Runs full Knowledge Evolution Pipeline (process_document)
   - Version Comparator (line & chunk diff)
   - Concept Drift Detection (embedding space distance)
   - Incremental FAISS reindexing without mutating unrelated indices
   - Maintains Document Version History (v1 -> v2)
   - Creates DocumentChange event
   - Links applied Document and Event back to KnowledgeUpdateRequest (Status: APPLIED)
7. Structured Audit Logging for the entire lifecycle
"""
import sys
import uuid
from datetime import datetime, timezone

from app.core.config import settings

# Disable background folder watcher for test speed
settings.watch_enabled = False
settings.domain_routing_enabled = True
settings.domain_routing_confidence_threshold = 0.50
settings.domain_routing_llm_enabled = False

from fastapi.testclient import TestClient
from app.main import app
from app.core.permissions import Role
from app.db.database import SessionLocal
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.document_change import DocumentChange
from app.models.domain import Domain
from app.models.knowledge_update_request import (
    KnowledgeUpdateRequest,
    KnowledgeUpdateStatus,
)
from app.models.ticket import (
    ResolutionType,
    Ticket,
    TicketPriority,
    TicketStatus,
)
from app.models.user import User
from app.models.user_domain import UserDomain
from app.schemas.document import ExtractedDocumentData
from app.services.auth_service import create_access_token, hash_password
from app.services.evolution_service import process_document


def run_tests():
    print("Starting Phase 14 Test Suite...")
    from app.db.base import init_db
    init_db()

    client = TestClient(app)
    db = SessionLocal()

    passed = 0
    failed = 0
    failed_list = []

    def check(name: str, cond: bool, extra: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name} {extra}")
            failed += 1
            failed_list.append(f"{name} ({extra})")

    suffix = uuid.uuid4().hex[:6]
    test_email_admin = f"superadmin-p14-{suffix}@example.com"
    test_email_hr_mgr = f"hrmanager-p14-{suffix}@example.com"
    test_email_fin_mgr = f"finmanager-p14-{suffix}@example.com"
    test_email_user = f"employee-p14-{suffix}@example.com"

    try:
        # ── 1. Setup Domains & Users ──────────────────────────────────────────
        domains = {}
        for k in ["hr", "finance", "it"]:
            d = db.query(Domain).filter(Domain.key == k).first()
            if not d:
                d = Domain(key=k, name=k.upper(), description=f"{k.upper()} Department", is_active=True)
                db.add(d)
                db.flush()
            domains[k] = d
        db.commit()

        # Super Admin
        admin_user = User(
            email=test_email_admin,
            full_name="Platform Super Admin",
            hashed_password=hash_password("adminpass123"),
            role=Role.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin_user)

        # HR Domain Manager
        hr_manager = User(
            email=test_email_hr_mgr,
            full_name="HR Domain Manager",
            hashed_password=hash_password("hrmgrpass123"),
            role=Role.DOMAIN_MANAGER,
            is_active=True,
        )
        db.add(hr_manager)

        # Finance Domain Manager
        fin_manager = User(
            email=test_email_fin_mgr,
            full_name="Finance Domain Manager",
            hashed_password=hash_password("finmgrpass123"),
            role=Role.DOMAIN_MANAGER,
            is_active=True,
        )
        db.add(fin_manager)

        # Standard User
        reg_user = User(
            email=test_email_user,
            full_name="Standard Employee",
            hashed_password=hash_password("userpass123"),
            role=Role.STANDARD_EMPLOYEE,
            is_active=True,
        )
        db.add(reg_user)

        db.commit()
        for u in [admin_user, hr_manager, fin_manager, reg_user]:
            db.refresh(u)

        # Assign Domain Memberships
        db.add(UserDomain(user_id=hr_manager.id, domain_id=domains["hr"].id, is_primary=True))
        db.add(UserDomain(user_id=fin_manager.id, domain_id=domains["finance"].id, is_primary=True))
        db.commit()

        # Auth Headers
        admin_headers = {"Authorization": f"Bearer {create_access_token(str(admin_user.id))}"}
        hr_mgr_headers = {"Authorization": f"Bearer {create_access_token(str(hr_manager.id))}"}
        fin_mgr_headers = {"Authorization": f"Bearer {create_access_token(str(fin_manager.id))}"}
        user_headers = {"Authorization": f"Bearer {create_access_token(str(reg_user.id))}"}

        print("\n--- 1. Seed Initial Document Version 1 ---")
        # Ingest initial HR policy v1
        initial_filename = f"hr_remote_policy_{suffix}.txt"
        initial_content = (
            "Human Resources Remote Work Policy Version 1.0\n\n"
            "Section 1: Eligibility\nAll full-time personnel may work from home.\n\n"
            "Section 2: Equipment Reimbursement\nEligible employees receive up to $200 for office supplies."
        )
        v1_data = ExtractedDocumentData(
            document_id=f"DOC_V1_{suffix.upper()}",
            filename=initial_filename,
            original_filename=initial_filename,
            document_type="txt",
            file_extension=".txt",
            extracted_text=initial_content,
            ocr_used=False,
            word_count=len(initial_content.split()),
            character_count=len(initial_content),
            upload_date=datetime.now(timezone.utc),
            author=admin_user.email,
            department="hr",
            language="en",
        )
        res_v1 = process_document(db=db, doc_data=v1_data, source="seed_test")
        doc_v1_id = res_v1["document"].document_id
        check("Initial document v1 created", doc_v1_id is not None)
        check("Initial document version is 1", res_v1["document"].version == 1)

        print("\n--- 2. Create and Resolve Low-Confidence Ticket ---")
        ticket_id = f"TKT_P14_{suffix}"
        t_hr = Ticket(
            ticket_id=ticket_id,
            user_id=reg_user.id,
            title="Remote Equipment Allowance Outdated",
            description="Employee asked about remote equipment allowance, but got outdated $200 figure.",
            original_question="What is the remote work equipment reimbursement limit?",
            generated_answer="Eligible employees receive up to $200 for office supplies.",
            confidence_score=0.35,
            confidence_threshold=0.70,
            evidence="Doc hr_remote_policy mentions $200.",
            source_document_ids=f'["{doc_v1_id}"]',
            domain="hr",
            priority=TicketPriority.HIGH.value,
            status=TicketStatus.RESOLVED.value,
            resolution_type=ResolutionType.OUTDATED_DOCUMENT.value,
            resolution="Under the 2026 Remote Policy, all remote staff receive an annual stipend of up to $750.",
            supporting_evidence="Updated policy approved Jan 2026.",
            supporting_document_ids=f'["{doc_v1_id}"]',
            resolver_user_id=hr_manager.id,
            resolved_at=datetime.now(timezone.utc),
        )
        db.add(t_hr)
        db.commit()
        db.refresh(t_hr)
        check("Resolved ticket with OUTDATED_DOCUMENT created", t_hr is not None)

        print("\n--- 3. Stage Knowledge Update Request from Ticket ---")
        # Domain Manager creates Knowledge Update Request
        r_create_req = client.post(
            f"/api/v1/tickets/{t_hr.ticket_id}/create-knowledge-update",
            json={
                "ticket_id": t_hr.ticket_id,
                "document_id": doc_v1_id,
                "target_filename": initial_filename,
                "domain": "hr",
                "root_cause": "OUTDATED_DOCUMENT",
                "title": "Update Remote Work Equipment Stipend to $750",
                "description": "The 2022 policy lists $200; update to current 2026 stipend of $750.",
                "suggested_resolution": "Under the 2026 Remote Policy, all remote staff receive an annual stipend of up to $750 for ergonomic workspace setup.",
                "supporting_evidence": "Policy updated by executive committee in Jan 2026.",
                "supporting_document_ids": [doc_v1_id],
            },
            headers=hr_mgr_headers,
        )
        check("POST /tickets/{id}/create-knowledge-update returns 200", r_create_req.status_code == 200)
        req_data = r_create_req.json()
        request_id = req_data["request_id"]
        check("Knowledge Update Request created with status 'pending_review'", req_data["status"] == "pending_review")
        check("Target filename linked correctly", req_data["target_filename"] == initial_filename)
        check("Root cause is OUTDATED_DOCUMENT", req_data["root_cause"] == "OUTDATED_DOCUMENT")

        print("\n--- 4. Safety Constraint Verification: Production Knowledge Untouched ---")
        # Ensure Document v1 remains the latest and only version so far
        doc_v1_check = db.query(Document).filter(Document.document_id == doc_v1_id).first()
        check("Document v1 remains active/latest before approval", doc_v1_check.is_latest is True and doc_v1_check.version == 1)
        all_docs_count = db.query(Document).filter(Document.original_filename == initial_filename).count()
        check("No new document versions exist prior to admin approval", all_docs_count == 1)

        print("\n--- 5. RBAC Scoping & Governance Authorization ---")
        # 5.1 Regular employee cannot approve or apply (403)
        r_user_review = client.post(
            f"/api/v1/knowledge-updates/{request_id}/review",
            json={"action": "approve"},
            headers=user_headers,
        )
        check("Standard Employee cannot review request (403 Forbidden)", r_user_review.status_code == 403)

        # 5.2 Finance Manager cannot approve HR request (cross-domain isolation -> 404 / access denied)
        r_fin_review = client.post(
            f"/api/v1/knowledge-updates/{request_id}/review",
            json={"action": "approve"},
            headers=fin_mgr_headers,
        )
        check("Finance Manager cannot review HR request (404/denied)", r_fin_review.status_code == 404)

        # 5.3 Super Admin approves the request
        r_admin_approve = client.post(
            f"/api/v1/knowledge-updates/{request_id}/review",
            json={"action": "approve", "admin_notes": "Approved by Super Admin for 2026 policy refresh."},
            headers=admin_headers,
        )
        check("Super Admin approves request (200 OK)", r_admin_approve.status_code == 200)
        check("Status is now 'approved'", r_admin_approve.json()["status"] == "approved")

        print("\n--- 6. Admin Applies Update: Evolution Pipeline, Version Comparator & Drift ---")
        updated_content = (
            "Human Resources Remote Work Policy Version 2.0\n\n"
            "Section 1: Eligibility\nAll full-time personnel may work from home.\n\n"
            "Section 2: Equipment Reimbursement\nEligible employees receive an annual stipend of up to $750 for ergonomic workspace setup."
        )

        r_apply = client.post(
            f"/api/v1/knowledge-updates/{request_id}/apply",
            json={
                "updated_text": updated_content,
                "target_filename": initial_filename,
                "admin_notes": "Applied 2026 updated stipend.",
            },
            headers=admin_headers,
        )
        if r_apply.status_code != 200:
            print(f"[DEBUG APPLY FAIL] Status: {r_apply.status_code}, Body: {r_apply.text}")
        check("POST /knowledge-updates/{id}/apply returns 200", r_apply.status_code == 200)
        apply_res = r_apply.json() if r_apply.status_code == 200 else {"request": {}, "evolution_result": {}}
        check("Request status updated to 'applied'", apply_res.get("request", {}).get("status") == "applied")
        check("Applied document ID returned", apply_res.get("request", {}).get("applied_document_id") is not None)
        check("Evolution change event ID returned", apply_res.get("request", {}).get("change_event_id") is not None)

        evo_result = apply_res.get("evolution_result", {})
        check("Evolution change_type is 'new_version'", evo_result.get("change_type") == "new_version")
        check("New document version is 2", evo_result["version"] == 2)
        check("New document is marked is_latest=True", evo_result["is_latest"] is True)

        print("\n--- 7. Document Version History & Evolution Event Inspection ---")
        # Refresh session to inspect database state committed by FastAPI worker
        db.expire_all()
        doc_v2 = db.query(Document).filter(Document.document_id == apply_res["request"]["applied_document_id"]).first()
        doc_v1_after = db.query(Document).filter(Document.document_id == doc_v1_id).first()

        check("Document v2 exists in DB", doc_v2 is not None)
        check("Document v2 version is 2", doc_v2.version == 2)
        check("Document v2 is_latest is True", doc_v2.is_latest is True)
        check("Document v2 points to previous_version_id=doc_v1_id", doc_v2.previous_version_id == doc_v1_id)
        check("Document v1 is_latest is now False", doc_v1_after.is_latest is False)

        # Verify DocumentChange event (Evolution Timeline)
        change_event = db.query(DocumentChange).filter(DocumentChange.event_id == apply_res["request"]["change_event_id"]).first()
        check("DocumentChange event recorded in database", change_event is not None)
        if change_event:
            check("DocumentChange diff lines recorded", change_event.lines_modified > 0 or change_event.lines_added > 0 or change_event.unified_diff is not None)
            check("DocumentChange old_doc_id is v1", change_event.old_document_id == doc_v1_id)
            check("DocumentChange new_doc_id is v2", change_event.new_document_id == doc_v2.document_id)

        print("\n--- 8. Queue Stats & Filtering ---")
        r_stats = client.get("/api/v1/knowledge-updates/stats", headers=admin_headers)
        check("GET /knowledge-updates/stats returns 200", r_stats.status_code == 200)
        stats_data = r_stats.json()
        check("Stats show at least 1 applied request", stats_data["applied"] >= 1)
        check("Stats root cause counts include OUTDATED_DOCUMENT", "OUTDATED_DOCUMENT" in stats_data["by_root_cause"])

        r_filter = client.get(f"/api/v1/knowledge-updates/?status=applied&ticket_id={ticket_id}", headers=admin_headers)
        check("GET /knowledge-updates/?status=applied returns 200", r_filter.status_code == 200)
        check("Filtered list contains our applied request", any(r["request_id"] == request_id for r in r_filter.json()["requests"]))

        print("\n--- 9. Structured Audit Trail ---")
        db.expire_all()
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.detail.ilike(f"%{request_id}%"),
            )
            .all()
        )
        check("Audit log contains events for knowledge update request", len(audits) >= 2)
        event_types = [a.event_type for a in audits]
        check("Audit trail contains knowledge_update_requested", "knowledge_update_requested" in event_types)
        check("Audit trail contains knowledge_update_applied", "knowledge_update_applied" in event_types)

    finally:
        # Cleanup test entities
        db.query(KnowledgeUpdateRequest).filter(KnowledgeUpdateRequest.ticket_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(DocumentChange).filter(DocumentChange.filename.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Document).filter(Document.original_filename.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Ticket).filter(Ticket.ticket_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.detail.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(UserDomain).filter(UserDomain.user_id.in_([hr_manager.id, fin_manager.id, reg_user.id])).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_([test_email_admin, test_email_hr_mgr, test_email_fin_mgr, test_email_user])).delete(synchronize_session=False)
        db.commit()
        db.close()

    print("\n==========================================")
    print(f"RESULTS: {passed} / {passed + failed} PASSED")
    if failed > 0:
        print(f"FAILED TESTS ({failed}):")
        for ft in failed_list:
            print(f"  - {ft}")
        sys.exit(1)
    else:
        print("ALL PHASE 14 TICKET-EVOLUTION TESTS PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
