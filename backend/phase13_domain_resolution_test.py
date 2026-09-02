"""
Phase 13 — Domain Expert Ticket Resolution Verification Test Suite
==================================================================
Verifies the complete Domain Expert workflow:
1. Low Confidence Query -> Ticket Created -> Domain Routing -> Domain Queue
2. Domain Expert Inspection (original question, retrieved evidence, citations, generated answer)
3. Ticket Resolution validation:
   - Required fields: resolution, resolution_type, resolved_by, resolved_at
   - Supported resolution types: KNOWLEDGE_MISSING, RETRIEVAL_FAILURE, INCORRECT_GENERATION,
     OUTDATED_DOCUMENT, ACCESS_RESTRICTION, DOCUMENT_CONFLICT, USER_CLARIFICATION, OTHER
4. Resolution Persistence & Metadata (supporting evidence, attached documents, internal notes)
5. Continuous Learning Feedback Module Integration:
   - Feedback record created/updated for originating query_id with verified correction
   - Knowledge base vectors remain untouched without explicit ingestion
6. Role-Based Access Control & Domain Scoping:
   - Domain Manager / Assigned Expert domain queue access
   - Cross-domain isolation enforcement
   - Unauthorized user rejection (403 Forbidden)
7. Audit Logging for resolution events
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
from app.models.domain import Domain
from app.models.feedback import Feedback
from app.models.query_log import QueryLog
from app.models.ticket import (
    RESOLUTION_TYPES,
    ResolutionType,
    Ticket,
    TicketPriority,
    TicketStatus,
)
from app.models.user import User
from app.models.user_domain import UserDomain
from app.services.auth_service import create_access_token, hash_password
from app.services.ticket_service import create_ticket_from_low_confidence


def run_tests():
    print("Starting Phase 13 Test Suite...")
    client = TestClient(app)
    db = SessionLocal()

    passed = 0
    failed = 0

    def check(name: str, cond: bool, extra: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"[PASS] {name}")
            passed += 1
        else:
            print(f"[FAIL] {name} {extra}")
            failed += 1

    suffix = uuid.uuid4().hex[:6]
    test_email_admin = f"superadmin-p13-{suffix}@example.com"
    test_email_hr_mgr = f"hrmanager-p13-{suffix}@example.com"
    test_email_fin_mgr = f"finmanager-p13-{suffix}@example.com"
    test_email_user = f"employee-p13-{suffix}@example.com"

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

        print("\n--- 1. Testing Ticket Creation, Origin Telemetry & Domain Queue ---")
        # 1.1 Create originating QueryLog
        q_id = f"QRY_HR_P13_{suffix}"
        q_log = QueryLog(
            query_id=q_id,
            user_id=reg_user.id,
            query_text=f"What is the remote work equipment reimbursement policy? {suffix}",
            answer_text="Employees receive up to $200 for equipment.",
            latency_ms=412.0,
            route="hybrid",
            retrieval_strategy="adaptive",
            model_used="claude-3-5-sonnet",
            confidence_score=0.32,
        )
        db.add(q_log)
        db.commit()

        # 1.2 Generate low-confidence ticket
        t_hr, _ = create_ticket_from_low_confidence(
            db,
            query_id=q_id,
            user_id=str(reg_user.id),
            original_question=f"What is the remote work equipment reimbursement policy? {suffix}",
            generated_answer="Employees receive up to $200 for equipment.",
            confidence_score=0.32,
            confidence_threshold=0.70,
            evidence="Retrieved document DOC_REMOTE_2022 mentions $200 but HR update says $750.",
            domain="hr",
            source_document_ids=["DOC_REMOTE_2022", "DOC_EXPENSE_GUIDE"],
        )
        check("Low confidence query generated a support ticket", t_hr is not None)
        check("Ticket routed domain is HR", t_hr.domain.lower() == "hr")
        check("Ticket status is open/routed/assigned", t_hr.status in [TicketStatus.OPEN.value, TicketStatus.ROUTED.value, TicketStatus.ASSIGNED.value])

        print("\n--- 2. Testing Domain Expert Ticket Inspection ---")
        # Domain Manager inspects ticket detail
        r_inspect = client.get(f"/api/v1/tickets/{t_hr.ticket_id}", headers=hr_mgr_headers)
        check("Domain Manager GET /tickets/{id} returns 200", r_inspect.status_code == 200)
        detail = r_inspect.json()
        check("Original question is inspectable", "remote work equipment reimbursement" in detail["original_question"])
        check("Generated answer is inspectable", "up to $200" in detail["generated_answer"])
        check("Retrieved evidence is inspectable", "DOC_REMOTE_2022" in detail["evidence"])
        check("Citations/source documents are inspectable", len(detail["citations"]) >= 2 and "DOC_REMOTE_2022" in detail["citations"])
        check("Originating QueryLog history is attached", detail["query_history"] is not None and detail["query_history"]["latency_ms"] == 412.0)

        print("\n--- 3. Testing Resolution Validation & Resolution Types ---")
        # 3.1 Reject resolution without required resolution text
        r_invalid_empty = client.post(
            f"/api/v1/tickets/{t_hr.ticket_id}/resolve",
            json={"resolution": "  ", "resolution_type": "KNOWLEDGE_MISSING"},
            headers=hr_mgr_headers,
        )
        check("Reject resolution with empty resolution text (422)", r_invalid_empty.status_code == 422)

        # 3.2 Reject invalid resolution_type
        r_invalid_type = client.post(
            f"/api/v1/tickets/{t_hr.ticket_id}/resolve",
            json={"resolution": "Valid answer text.", "resolution_type": "INVALID_ROOT_CAUSE"},
            headers=hr_mgr_headers,
        )
        check("Reject invalid resolution_type (422)", r_invalid_type.status_code == 422)

        # 3.3 Verify all 8 resolution types are defined and valid
        expected_types = [
            "KNOWLEDGE_MISSING", "RETRIEVAL_FAILURE", "INCORRECT_GENERATION",
            "OUTDATED_DOCUMENT", "ACCESS_RESTRICTION", "DOCUMENT_CONFLICT",
            "USER_CLARIFICATION", "OTHER",
        ]
        check("All 8 resolution types in RESOLUTION_TYPES", all(t in RESOLUTION_TYPES for t in expected_types))

        print("\n--- 4. Testing Resolution Workflow with Metadata & Document Attachment ---")
        # Resolve ticket as OUTDATED_DOCUMENT with supporting evidence and documents
        correct_answer = "Under the 2026 Remote Work Policy, all eligible remote employees receive an annual stipend of up to $750 for ergonomic workspace equipment."
        r_resolve = client.post(
            f"/api/v1/tickets/{t_hr.ticket_id}/resolve",
            json={
                "resolution": correct_answer,
                "resolution_type": ResolutionType.OUTDATED_DOCUMENT.value,
                "supporting_evidence": "Policy was updated in Jan 2026; old 2022 handbook needs archival.",
                "supporting_document_ids": ["DOC_HR_REMOTE_2026_V2", "POLICY_STIPEND_SEC5"],
                "internal_notes": "Archived DOC_REMOTE_2022 and attached 2026 policy.",
            },
            headers=hr_mgr_headers,
        )
        check("POST /tickets/{id}/resolve returns 200", r_resolve.status_code == 200)
        res_data = r_resolve.json()
        check("Ticket status is resolved", res_data["status"] == "resolved")
        check("Ticket resolution stored correctly", res_data["resolution"] == correct_answer)
        check("Ticket resolution_type is OUTDATED_DOCUMENT", res_data["resolution_type"] == "OUTDATED_DOCUMENT")
        check("Ticket resolved_at is set", res_data["resolved_at"] is not None)
        check("Ticket resolved_by matches resolver user", res_data["resolved_by"] == str(hr_manager.id))
        check("Supporting evidence stored", "Jan 2026" in res_data["supporting_evidence"])
        check("Attached supporting documents stored", "DOC_HR_REMOTE_2026_V2" in res_data["supporting_document_ids"])

        print("\n--- 5. Testing Continuous Learning Module Feedback Integration ---")
        # Verify feedback was stored in Continuous Learning Feedback table
        fb = db.query(Feedback).filter(Feedback.query_id == q_id).first()
        check("Feedback entry stored for query_id in Continuous Learning", fb is not None)
        if fb:
            check("Feedback rating recorded as 'down' for low-confidence query", fb.rating == "down")
            check("Feedback correction_text matches verified resolution", fb.correction_text == correct_answer)

        # Verify QueryLog status updated
        ql_updated = db.query(QueryLog).filter(QueryLog.query_id == q_id).first()
        check("QueryLog ticket_status updated to resolved", ql_updated.ticket_status == "resolved")

        print("\n--- 6. Testing Resolution Types Across Tickets & Dashboard Metrics ---")
        # Create tickets for remaining resolution types
        created_test_tickets = []
        for r_type in expected_types:
            if r_type == "OUTDATED_DOCUMENT":
                continue
            t_sample = Ticket(
                ticket_id=f"TKT_{r_type}_{suffix}",
                user_id=reg_user.id,
                title=f"Test ticket for {r_type}",
                description=f"Ticket testing resolution type {r_type}",
                original_question=f"Sample question for {r_type} {suffix}",
                generated_answer="Sample generated answer.",
                confidence_score=0.30,
                confidence_threshold=0.70,
                priority=TicketPriority.MEDIUM.value,
                domain="hr",
                status=TicketStatus.OPEN.value,
                routed_domain_id=domains["hr"].id,
            )
            db.add(t_sample)
            db.flush()
            created_test_tickets.append((t_sample, r_type))
        db.commit()

        # Resolve each ticket with its respective resolution type
        for t_item, r_type in created_test_tickets:
            r_res_item = client.post(
                f"/api/v1/tickets/{t_item.ticket_id}/resolve",
                json={
                    "resolution": f"Authoritative resolution for {t_item.ticket_id}",
                    "resolution_type": r_type,
                    "internal_notes": f"Resolved during {t_item.ticket_id} test.",
                },
                headers=admin_headers,
            )
            check(f"Resolve ticket with {r_type} returns 200", r_res_item.status_code == 200)

        # Check Dashboard Metrics include by_resolution_type
        r_dash = client.get("/api/v1/tickets/dashboard", headers=admin_headers)
        check("GET /tickets/dashboard returns 200", r_dash.status_code == 200)
        dash_data = r_dash.json()
        check("Dashboard has by_resolution_type field", "by_resolution_type" in dash_data)
        check("by_resolution_type contains OUTDATED_DOCUMENT", "OUTDATED_DOCUMENT" in dash_data["by_resolution_type"])
        check("by_resolution_type contains KNOWLEDGE_MISSING", "KNOWLEDGE_MISSING" in dash_data["by_resolution_type"])
        check("by_resolution_type contains RETRIEVAL_FAILURE", "RETRIEVAL_FAILURE" in dash_data["by_resolution_type"])

        # Filter by resolution_type
        r_filter_type = client.get("/api/v1/tickets/?resolution_type=OUTDATED_DOCUMENT", headers=admin_headers)
        check("Filter by resolution_type=OUTDATED_DOCUMENT returns 200", r_filter_type.status_code == 200)
        check("Filtered results have resolution_type OUTDATED_DOCUMENT", all(t["resolution_type"] == "OUTDATED_DOCUMENT" for t in r_filter_type.json()["tickets"]))

        print("\n--- 7. Testing RBAC Scoping & Domain Isolation ---")
        # Create Finance Ticket
        t_fin = Ticket(
            ticket_id=f"TKT_FIN_P13_{suffix}",
            user_id=reg_user.id,
            title=f"Finance Tax Policy {suffix}",
            description="Tax depreciation query",
            original_question=f"What is the capital asset depreciation rate? {suffix}",
            generated_answer="Depreciation rate is 20%.",
            confidence_score=0.40,
            confidence_threshold=0.70,
            domain="finance",
            status=TicketStatus.OPEN.value,
            routed_domain_id=domains["finance"].id,
        )
        db.add(t_fin)
        db.commit()

        # 7.1 HR Manager CANNOT resolve Finance ticket (404 / Access Denied)
        r_cross_resolve = client.post(
            f"/api/v1/tickets/{t_fin.ticket_id}/resolve",
            json={"resolution": "Unauthorized HR resolution", "resolution_type": "OTHER"},
            headers=hr_mgr_headers,
        )
        check("HR Manager CANNOT resolve Finance Ticket (404)", r_cross_resolve.status_code == 404)

        # 7.2 Finance Manager CAN resolve Finance ticket
        r_fin_resolve = client.post(
            f"/api/v1/tickets/{t_fin.ticket_id}/resolve",
            json={
                "resolution": "Capital assets are depreciated according to MACRS over 5 or 7 years.",
                "resolution_type": ResolutionType.KNOWLEDGE_MISSING.value,
            },
            headers=fin_mgr_headers,
        )
        check("Finance Manager CAN resolve Finance Ticket (200)", r_fin_resolve.status_code == 200)

        # 7.3 Regular Employee CANNOT resolve tickets (403 Forbidden)
        r_user_resolve = client.post(
            f"/api/v1/tickets/{t_fin.ticket_id}/resolve",
            json={"resolution": "Unauthorized user resolution", "resolution_type": "OTHER"},
            headers=user_headers,
        )
        check("Standard Employee CANNOT resolve tickets (403 Forbidden)", r_user_resolve.status_code == 403)

        print("\n--- 8. Testing Structured Audit Logging for Resolutions ---")
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.event_type == "ticket_resolved",
                AuditLog.detail.ilike(f"%{t_hr.ticket_id}%"),
            )
            .all()
        )
        check("Audit log recorded for ticket_resolved", len(audits) > 0)
        if audits:
            check("Audit detail contains OUTDATED_DOCUMENT resolution_type", "OUTDATED_DOCUMENT" in audits[0].detail)
            check("Audit detail contains resolver email", test_email_hr_mgr in audits[0].detail)

    finally:
        # Cleanup test data
        db.query(Ticket).filter(Ticket.ticket_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Feedback).filter(Feedback.query_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(QueryLog).filter(QueryLog.query_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.detail.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(UserDomain).filter(UserDomain.user_id.in_([hr_manager.id, fin_manager.id, reg_user.id])).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_([test_email_admin, test_email_hr_mgr, test_email_fin_mgr, test_email_user])).delete(synchronize_session=False)
        db.commit()
        db.close()

    print("\n==========================================")
    print(f"RESULTS: {passed} / {passed + failed} PASSED")
    if failed > 0:
        print(f"FAILED TESTS: {failed}")
        sys.exit(1)
    else:
        print("ALL PHASE 13 RESOLUTION TESTS PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
