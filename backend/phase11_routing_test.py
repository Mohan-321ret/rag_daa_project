"""
Phase 11 — Domain-Based Ticket Routing Verification Test Suite
==============================================================
Tests all 6 cascading classification strategies in priority order,
uncertainty handling / NEEDS_TRIAGE fallback, domain manager auto-assignment,
audit logging, and REST API endpoints.
"""
import sys
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.permissions import Role
from app.db.database import SessionLocal
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.document import Document
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.models.audit_log import AuditLog
from app.services.auth_service import create_access_token, hash_password
from app.services.domain_router_service import classify_domain, route_ticket, assign_domain_manager


def run_tests():
    # Disable background folder watcher and heavy components for fast test execution
    settings.watch_enabled = False
    settings.domain_routing_enabled = True
    settings.domain_routing_confidence_threshold = 0.50
    settings.domain_routing_llm_enabled = False  # Keep deterministic for unit tests

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
    test_email_admin = f"admin-route-{suffix}@example.com"
    test_email_hr_mgr = f"hr-mgr-{suffix}@example.com"
    test_email_user = f"user-route-{suffix}@example.com"

    try:
        # ── Setup Test Entities ───────────────────────────────────────────────
        # Ensure standard domains exist
        domain_keys = ["hr", "finance", "it", "legal", "engineering"]
        domains = {}
        for k in domain_keys:
            d = db.query(Domain).filter(Domain.key == k).first()
            if not d:
                d = Domain(key=k, name=k.upper(), description=f"{k.upper()} Department", is_active=True)
                db.add(d)
                db.flush()
            domains[k] = d
        db.commit()

        # Create Admin
        admin_user = User(
            email=test_email_admin,
            full_name="Routing Admin",
            hashed_password=hash_password("adminpass123"),
            role=Role.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin_user)

        # Create HR Manager
        hr_manager = User(
            email=test_email_hr_mgr,
            full_name="HR Manager Expert",
            hashed_password=hash_password("mgrpass123"),
            role=Role.DOMAIN_MANAGER,
            is_active=True,
        )
        db.add(hr_manager)

        # Create Regular User with IT domain
        reg_user = User(
            email=test_email_user,
            full_name="Regular Employee",
            hashed_password=hash_password("userpass123"),
            role=Role.STANDARD_EMPLOYEE,
            is_active=True,
        )
        db.add(reg_user)

        # Create Unassigned User (no default domain)
        test_email_unassigned = f"unassigned-{suffix}@example.com"
        unassigned_user = User(
            email=test_email_unassigned,
            full_name="Unassigned Employee",
            hashed_password=hash_password("userpass123"),
            role=Role.STANDARD_EMPLOYEE,
            is_active=True,
        )
        db.add(unassigned_user)

        db.commit()
        db.refresh(admin_user)
        db.refresh(hr_manager)
        db.refresh(reg_user)
        db.refresh(unassigned_user)

        # Assign HR Manager as primary manager for HR domain
        assign_domain_manager(db, domain_id=domains["hr"].id, manager_user_id=hr_manager.id, is_primary=True)

        # Assign Regular User to IT domain as primary
        user_domain_link = UserDomain(user_id=reg_user.id, domain_id=domains["it"].id, is_primary=True)
        db.add(user_domain_link)
        db.commit()

        # Auth headers
        admin_token = create_access_token(str(admin_user.id))
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        user_token = create_access_token(str(reg_user.id))
        user_headers = {"Authorization": f"Bearer {user_token}"}

        print("\n--- 1. Testing Strategy 1: Explicit User-Selected Domain ---")
        # Direct service test
        import asyncio
        res1 = asyncio.run(classify_domain(
            db,
            query_text="Generic question about anything",
            explicit_domain="finance",
        ))
        check("Strategy 1: Explicit domain returns Finance", res1.domain_key == "finance")
        check("Strategy 1: Confidence is 1.00", res1.confidence == 1.0)
        check("Strategy 1: Method is user_selected", res1.method == "user_selected")
        check("Strategy 1: needs_triage is False", res1.needs_triage is False)

        print("\n--- 2. Testing Strategy 2: User's Assigned Domain ---")
        res2 = asyncio.run(classify_domain(
            db,
            query_text="A general ambiguous query with no strong keywords",
            user_id=str(reg_user.id),
        ))
        check("Strategy 2: User assigned domain routes to IT", res2.domain_key == "it")
        check("Strategy 2: Method is user_domain", res2.method == "user_domain")
        check("Strategy 2: Confidence >= 0.80", res2.confidence >= 0.80)

        print("\n--- 3. Testing Strategy 3: Query Intelligence / Intent & Keywords ---")
        # Test HR Query
        res3_hr = asyncio.run(classify_domain(
            db,
            query_text="What is the maternity leave policy?",
        ))
        check("Strategy 3: 'maternity leave' routes to HR", res3_hr.domain_key == "hr")
        check("Strategy 3: Method is intent_keywords", res3_hr.method == "intent_keywords")

        # Test Finance Query
        res3_fin = asyncio.run(classify_domain(
            db,
            query_text="What is the invoice approval process?",
        ))
        check("Strategy 3: 'invoice approval' routes to Finance", res3_fin.domain_key == "finance")

        # Test IT Query
        res3_it = asyncio.run(classify_domain(
            db,
            query_text="How do I reset my corporate VPN?",
        ))
        check("Strategy 3: 'reset corporate VPN' routes to IT", res3_it.domain_key == "it")

        # Test Legal Query
        res3_legal = asyncio.run(classify_domain(
            db,
            query_text="What are our NDA and compliance regulations for contracts?",
        ))
        check("Strategy 3: 'NDA compliance' routes to Legal", res3_legal.domain_key == "legal")

        print("\n--- 4. Testing Strategy 4: Named Entities Mapping ---")
        class MockEntity:
            def __init__(self, text):
                self.text = text

        res4 = asyncio.run(classify_domain(
            db,
            query_text="General request for information",
            entities=[MockEntity("payroll"), MockEntity("appraisal")],
        ))
        check("Strategy 4: Entities 'payroll, appraisal' route to HR", res4.domain_key == "hr")
        check("Strategy 4: Method is ner_entities", res4.method == "ner_entities")

        print("\n--- 5. Testing Strategy 5: Retrieved Document Domains ---")
        # Create a document belonging to Engineering
        test_doc_id = f"DOC_ENG_{suffix}"
        eng_doc = Document(
            document_id=test_doc_id,
            filename="deploy_guide.pdf",
            original_filename="deploy_guide.pdf",
            document_type="PDF",
            file_extension=".pdf",
            domain_id=domains["engineering"].id,
        )
        db.add(eng_doc)
        db.commit()

        res5 = asyncio.run(classify_domain(
            db,
            query_text="Random generic ambiguous inquiry",
            source_document_ids=[test_doc_id],
        ))
        check("Strategy 5: Document domain routes to Engineering", res5.domain_key == "engineering")
        check("Strategy 5: Method is document_domain", res5.method == "document_domain")

        print("\n--- 6. Testing Strategy 7: Uncertainty & NEEDS_TRIAGE Fallback ---")
        res_triage = asyncio.run(classify_domain(
            db,
            query_text="xyzqwerty987123 foobarbaz unmatched gibberish",
        ))
        check("Uncertainty: needs_triage is True", res_triage.needs_triage is True)
        check("Uncertainty: Method is needs_triage", res_triage.method == "needs_triage")
        check("Uncertainty: Domain key is None", res_triage.domain_key is None)

        print("\n--- 7. Testing Ticket Routing & Auto-Assignment ---")
        from app.services.ticket_service import create_ticket_from_low_confidence

        # 7.1 Route via Strategy 2 (User Domain)
        t_user_dom, _ = create_ticket_from_low_confidence(
            db,
            query_id=f"QRY_USERDOM_{suffix}",
            user_id=str(reg_user.id),
            original_question=f"Ambiguous general query from IT employee {suffix}",
            generated_answer="Some generic answer.",
            confidence_score=0.30,
            confidence_threshold=0.70,
        )
        check("User Domain Ticket routed to IT", t_user_dom.domain.lower() == "it")
        check("User Domain Ticket method is user_domain", t_user_dom.routing_method == "user_domain")

        # 7.2 Route to HR via Strategy 3 (Intent/Keywords) -> should auto-assign to HR Manager
        t_hr, msg_hr = create_ticket_from_low_confidence(
            db,
            query_id=f"QRY_HR_{suffix}",
            user_id=str(unassigned_user.id),
            original_question=f"What is the maternity leave policy for new parents? {suffix}",
            generated_answer="I think leave might be 12 weeks maybe.",
            confidence_score=0.35,
            confidence_threshold=0.70,
        )
        check("HR Ticket created", t_hr is not None)
        check("HR Ticket status is ROUTED", t_hr.status == TicketStatus.ROUTED.value)
        check("HR Ticket domain is HR", t_hr.domain.lower() == "hr")
        check("HR Ticket assigned to HR Manager", str(t_hr.assigned_to) == str(hr_manager.id))
        check("HR Ticket routing confidence recorded", t_hr.routing_confidence > 0.0)
        check("HR Ticket routing method is intent_keywords", t_hr.routing_method == "intent_keywords")
        check("HR Ticket routing timestamp recorded", t_hr.routing_timestamp is not None)

        # 7.3 Route Uncertain Query -> should mark NEEDS_TRIAGE and assign to Admin
        t_triage, _ = create_ticket_from_low_confidence(
            db,
            query_id=f"QRY_TRIAGE_{suffix}",
            user_id=str(unassigned_user.id),
            original_question=f"xyzqwerty112233 gibberish unclassifiable query? {suffix}",
            generated_answer="Unknown answer text.",
            confidence_score=0.20,
            confidence_threshold=0.70,
        )
        check("Triage Ticket created", t_triage is not None)
        check("Triage Ticket status is NEEDS_TRIAGE", t_triage.status == TicketStatus.NEEDS_TRIAGE.value)
        check("Triage Ticket needs_triage is True", t_triage.needs_triage is True)
        assigned_admin = db.query(User).filter(User.id == t_triage.assigned_to).first()
        check("Triage Ticket assigned to Super Admin", assigned_admin is not None and assigned_admin.role in (Role.SUPER_ADMIN.value, Role.PLATFORM_OWNER.value))

        print("\n--- 8. Testing Audit Logging for Routing Events ---")
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.detail.ilike(f"%{t_hr.ticket_id}%"))
            .all()
        )
        check("Audit log recorded for HR ticket routing", len(audits) >= 1)
        if audits:
            check("Audit event_type is ticket_routed", audits[0].event_type == "ticket_routed")

        triage_audits = (
            db.query(AuditLog)
            .filter(AuditLog.detail.ilike(f"%{t_triage.ticket_id}%"))
            .all()
        )
        check("Audit log recorded for Triage ticket", len(triage_audits) >= 1)
        if triage_audits:
            check("Audit event_type is ticket_triage_needed", triage_audits[0].event_type == "ticket_triage_needed")

        print("\n--- 9. Testing REST API Endpoints ---")
        # 9.1 GET /api/v1/domain-routing/config
        r_cfg = client.get("/api/v1/domain-routing/config", headers=user_headers)
        check("GET /domain-routing/config returns 200", r_cfg.status_code == 200)
        check("Config contains threshold", "domain_routing_confidence_threshold" in r_cfg.json())

        # 9.2 PATCH /api/v1/domain-routing/config (Non-admin 403 vs Admin 200)
        r_patch_fail = client.patch(
            "/api/v1/domain-routing/config",
            json={"domain_routing_confidence_threshold": 0.60},
            headers=user_headers,
        )
        check("Non-admin PATCH /domain-routing/config returns 403", r_patch_fail.status_code == 403)

        r_patch_ok = client.patch(
            "/api/v1/domain-routing/config",
            json={"domain_routing_confidence_threshold": 0.55},
            headers=admin_headers,
        )
        check("Admin PATCH /domain-routing/config returns 200", r_patch_ok.status_code == 200)
        check("Threshold updated to 0.55", r_patch_ok.json()["domain_routing_confidence_threshold"] == 0.55)

        # 9.3 Domain Manager listing via API
        hr_domain_id = str(domains["hr"].id)
        r_mgrs = client.get(f"/api/v1/domain-routing/domains/{hr_domain_id}/managers", headers=user_headers)
        check("GET /domains/{id}/managers returns 200", r_mgrs.status_code == 200)
        check("HR Manager in list", any(m["manager_email"] == test_email_hr_mgr for m in r_mgrs.json()))

        # 9.4 Classify API
        r_classify = client.post(
            "/api/v1/domain-routing/classify",
            json={"query_text": "What is the corporate invoice approval policy?"},
            headers=user_headers,
        )
        check("POST /domain-routing/classify returns 200", r_classify.status_code == 200)
        check("Classify returns Finance", r_classify.json()["domain_key"] == "finance")

        # 9.5 Admin Manual Reroute API
        r_reroute = client.post(
            f"/api/v1/domain-routing/tickets/{t_triage.ticket_id}/reroute",
            json={"domain_key": "finance", "reviewer_notes": "Rerouted to Finance after manual review"},
            headers=admin_headers,
        )
        check("Admin POST /tickets/{id}/reroute returns 200", r_reroute.status_code == 200)
        check("Ticket domain changed to finance", r_reroute.json()["domain"] == "finance")
        check("Ticket status changed to routed", r_reroute.json()["status"] == "routed")
        check("Ticket needs_triage is False", r_reroute.json()["needs_triage"] is False)

    finally:
        # Cleanup
        db.query(Ticket).filter(Ticket.original_question.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Document).filter(Document.document_id == f"DOC_ENG_{suffix}").delete(synchronize_session=False)
        if 'reg_user' in locals() and reg_user and hasattr(reg_user, 'id'):
            db.query(UserDomain).filter(UserDomain.user_id == reg_user.id).delete(synchronize_session=False)
        if 'hr_manager' in locals() and hr_manager and hasattr(hr_manager, 'id'):
            db.query(DomainRoutingConfig).filter(DomainRoutingConfig.manager_user_id == hr_manager.id).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_([test_email_admin, test_email_hr_mgr, test_email_user, test_email_unassigned])).delete(synchronize_session=False)
        db.commit()
        db.close()

    print("\n==========================================")
    print(f"RESULTS: {passed} / {passed + failed} PASSED")
    if failed > 0:
        print(f"FAILED TESTS: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
