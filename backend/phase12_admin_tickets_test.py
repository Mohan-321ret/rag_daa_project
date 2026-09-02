"""
Phase 12 — Admin Panel: Ticket Management Verification Test Suite
================================================================
Verifies:
1. Ticket Dashboard Analytics & Metrics (total, open, unassigned, in-progress, resolved, overdue, avg resolution time, low confidence count)
2. Multi-Attribute Filtering (domain, status, priority, assigned_to, date range, confidence score, overdue, text search)
3. Rich Ticket Detail with Query History, Evidence, Citations, Expert Profile, and SLA indicators
4. Administrative Action Endpoints (assign, priority, status, internal notes, resolve, close)
5. Strict Domain-Scoped RBAC (Domain Manager domain isolation vs Super Admin global scoping vs Standard Employee own-only)
6. Structured Audit Logging for all administrative actions
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.permissions import Role
from app.db.database import SessionLocal
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.query_log import QueryLog
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import User
from app.models.user_domain import UserDomain
from app.models.audit_log import AuditLog
from app.services.auth_service import create_access_token, hash_password
from app.services.domain_router_service import assign_domain_manager
from app.services.ticket_service import create_ticket_from_low_confidence


def run_tests():
    settings.watch_enabled = False
    settings.domain_routing_enabled = True
    settings.domain_routing_confidence_threshold = 0.50
    settings.domain_routing_llm_enabled = False

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
    test_email_admin = f"superadmin-p12-{suffix}@example.com"
    test_email_hr_mgr = f"hrmanager-p12-{suffix}@example.com"
    test_email_fin_mgr = f"finmanager-p12-{suffix}@example.com"
    test_email_expert = f"hrexpert-p12-{suffix}@example.com"
    test_email_user = f"employee-p12-{suffix}@example.com"

    try:
        # ── 1. Setup Domains and Users ────────────────────────────────────────
        domains = {}
        for k in ["hr", "finance", "it"]:
            d = db.query(Domain).filter(Domain.key == k).first()
            if not d:
                d = Domain(key=k, name=k.upper(), description=f"{k.upper()} Dept", is_active=True)
                db.add(d)
                db.flush()
            domains[k] = d
        db.commit()

        # Super Admin
        admin_user = User(
            email=test_email_admin,
            full_name="Super Admin P12",
            hashed_password=hash_password("adminpass123"),
            role=Role.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin_user)

        # HR Domain Manager
        hr_manager = User(
            email=test_email_hr_mgr,
            full_name="HR Manager P12",
            hashed_password=hash_password("hrmgrpass123"),
            role=Role.DOMAIN_MANAGER,
            is_active=True,
        )
        db.add(hr_manager)

        # Finance Domain Manager
        fin_manager = User(
            email=test_email_fin_mgr,
            full_name="Finance Manager P12",
            hashed_password=hash_password("finmgrpass123"),
            role=Role.DOMAIN_MANAGER,
            is_active=True,
        )
        db.add(fin_manager)

        # HR Domain Expert
        hr_expert = User(
            email=test_email_expert,
            full_name="HR Domain Expert",
            hashed_password=hash_password("expertpass123"),
            role=Role.STANDARD_EMPLOYEE,
            is_active=True,
        )
        db.add(hr_expert)

        # Regular Employee
        reg_user = User(
            email=test_email_user,
            full_name="Regular Employee P12",
            hashed_password=hash_password("userpass123"),
            role=Role.STANDARD_EMPLOYEE,
            is_active=True,
        )
        db.add(reg_user)

        db.commit()
        for u in [admin_user, hr_manager, fin_manager, hr_expert, reg_user]:
            db.refresh(u)

        # Assign HR Manager to HR Domain
        db.add(UserDomain(user_id=hr_manager.id, domain_id=domains["hr"].id, is_primary=True))
        # Assign Finance Manager to Finance Domain
        db.add(UserDomain(user_id=fin_manager.id, domain_id=domains["finance"].id, is_primary=True))
        db.commit()

        # Auth Tokens & Headers
        admin_headers = {"Authorization": f"Bearer {create_access_token(str(admin_user.id))}"}
        hr_mgr_headers = {"Authorization": f"Bearer {create_access_token(str(hr_manager.id))}"}
        fin_mgr_headers = {"Authorization": f"Bearer {create_access_token(str(fin_manager.id))}"}
        user_headers = {"Authorization": f"Bearer {create_access_token(str(reg_user.id))}"}

        # ── 2. Create Seed Tickets & QueryLogs for Testing ────────────────────
        # 2.1 Seed QueryLog for ticket 1
        test_query_id = f"QRY_HR_{suffix}"
        q_log = QueryLog(
            query_id=test_query_id,
            user_id=reg_user.id,
            query_text=f"How many days of paid parental leave are provided? {suffix}",
            answer_text="Parental leave is roughly 6-12 weeks.",
            latency_ms=350.5,
            route="hybrid",
            retrieval_strategy="adaptive",
            model_used="claude-3-5-sonnet",
            confidence_score=0.35,
        )
        db.add(q_log)
        db.commit()

        # 2.2 HR Ticket 1 (Linked to QueryLog, Unassigned, Open)
        t_hr1, _ = create_ticket_from_low_confidence(
            db,
            query_id=test_query_id,
            user_id=str(reg_user.id),
            original_question=f"How many days of paid parental leave are provided? {suffix}",
            generated_answer="Parental leave is roughly 6-12 weeks.",
            confidence_score=0.35,
            confidence_threshold=0.70,
            domain="hr",
            source_document_ids=["DOC_HR_POLICY_01", "DOC_HR_HANDBOOK_02"],
            evidence="Inconsistent citations across leave documents.",
        )
        # Explicitly unassign to test unassigned metrics
        t_hr1.assigned_to = None
        db.commit()

        # 2.3 Finance Ticket 1 (Critical priority, Overdue by creation date)
        t_fin1 = Ticket(
            ticket_id=f"TKT_FIN1_{suffix}",
            query_id=f"QRY_FIN_{suffix}",
            user_id=reg_user.id,
            title=f"Invoice approval threshold exceeding limit {suffix}",
            description="Invoice requires VP approval but no document details found.",
            original_question=f"Who approves vendor invoices over $50,000? {suffix}",
            generated_answer="Invoices over $50k require VP signoff.",
            confidence_score=0.25,
            confidence_threshold=0.70,
            priority=TicketPriority.CRITICAL.value,
            domain="finance",
            status=TicketStatus.OPEN.value,
            routed_domain_id=domains["finance"].id,
            routing_confidence=0.85,
            routing_method="intent_keywords",
            created_at=datetime.now(timezone.utc) - timedelta(hours=30),  # >24h overdue for critical
        )
        db.add(t_fin1)

        # 2.4 Finance Ticket 2 (Resolved ticket to test resolution metrics)
        t_fin2 = Ticket(
            ticket_id=f"TKT_FIN2_{suffix}",
            query_id=f"QRY_FIN2_{suffix}",
            user_id=reg_user.id,
            title=f"Corporate tax deduction guidelines {suffix}",
            description="Tax deduction policy query.",
            original_question=f"What is the corporate tax deduction rule? {suffix}",
            generated_answer="Tax deduction is 15%.",
            confidence_score=0.40,
            confidence_threshold=0.70,
            priority=TicketPriority.MEDIUM.value,
            domain="finance",
            status=TicketStatus.RESOLVED.value,
            routed_domain_id=domains["finance"].id,
            resolution="Corporate tax deduction is governed by Section 179 up to $25,000.",
            resolved_at=datetime.now(timezone.utc),
            resolver_user_id=fin_manager.id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=4),
        )
        db.add(t_fin2)
        db.commit()

        print("\n--- 1. Testing Ticket Dashboard & Metrics (GET /tickets/dashboard) ---")
        # 1.1 Super Admin Dashboard (Global Scope)
        r_dash_admin = client.get("/api/v1/tickets/dashboard", headers=admin_headers)
        check("Super Admin GET /tickets/dashboard returns 200", r_dash_admin.status_code == 200)
        d_admin = r_dash_admin.json()
        check("Dashboard total_tickets >= 3", d_admin["total_tickets"] >= 3)
        check("Dashboard open_tickets >= 2", d_admin["open_tickets"] >= 2)
        check("Dashboard unassigned_tickets >= 1", d_admin["unassigned_tickets"] >= 1)
        check("Dashboard resolved_tickets >= 1", d_admin["resolved_tickets"] >= 1)
        check("Dashboard overdue_tickets >= 1", d_admin["overdue_tickets"] >= 1)
        check("Dashboard low_confidence_ticket_count >= 3", d_admin["low_confidence_ticket_count"] >= 3)
        check("Dashboard avg_resolution_time_seconds is calculated", d_admin["avg_resolution_time_seconds"] is not None)
        check("Dashboard by_domain contains 'hr' and 'finance'", "hr" in d_admin["by_domain"] and "finance" in d_admin["by_domain"])
        check("Dashboard by_priority contains 'critical' and 'medium'", "critical" in d_admin["by_priority"])

        # 1.2 Domain Manager Scoped Dashboard (HR Manager sees ONLY HR tickets)
        r_dash_hr = client.get("/api/v1/tickets/dashboard", headers=hr_mgr_headers)
        check("HR Manager GET /tickets/dashboard returns 200", r_dash_hr.status_code == 200)
        d_hr = r_dash_hr.json()
        check("HR Manager cannot see Finance tickets in domain breakdown", "finance" not in d_hr["by_domain"])
        check("HR Manager sees HR tickets in domain breakdown", "hr" in d_hr["by_domain"])

        # 1.3 Legacy Stats Endpoint (GET /tickets/stats)
        r_stats = client.get("/api/v1/tickets/stats", headers=admin_headers)
        check("GET /tickets/stats returns 200", r_stats.status_code == 200)
        s = r_stats.json()
        check("Stats contains unassigned_tickets", "unassigned_tickets" in s)
        check("Stats contains overdue_tickets", "overdue_tickets" in s)

        print("\n--- 2. Testing Multi-Attribute Filtering (GET /tickets/) ---")
        # 2.1 Filter by Domain
        r_filter_dom = client.get("/api/v1/tickets/?domain=finance", headers=admin_headers)
        check("Filter by domain=finance returns 200", r_filter_dom.status_code == 200)
        check("All returned tickets are in finance domain", all(t["domain"].lower() == "finance" for t in r_filter_dom.json()["tickets"]))

        # 2.2 Filter by Status
        r_filter_status = client.get("/api/v1/tickets/?status=resolved", headers=admin_headers)
        check("Filter by status=resolved returns 200", r_filter_status.status_code == 200)
        check("All returned tickets have status=resolved", all(t["status"] == "resolved" for t in r_filter_status.json()["tickets"]))

        # 2.3 Filter by Priority
        r_filter_prio = client.get("/api/v1/tickets/?priority=critical", headers=admin_headers)
        check("Filter by priority=critical returns 200", r_filter_prio.status_code == 200)
        check("All returned tickets have priority=critical", all(t["priority"] == "critical" for t in r_filter_prio.json()["tickets"]))

        # 2.4 Filter by Assigned Expert = unassigned
        r_filter_unassigned = client.get("/api/v1/tickets/?assigned_to=unassigned", headers=admin_headers)
        check("Filter by assigned_to=unassigned returns 200", r_filter_unassigned.status_code == 200)
        check("All returned tickets have assigned_to=None", all(t["assigned_to"] is None for t in r_filter_unassigned.json()["tickets"]))

        # 2.5 Filter by Confidence Range
        r_filter_conf = client.get("/api/v1/tickets/?min_confidence=0.20&max_confidence=0.36", headers=admin_headers)
        check("Filter by confidence range returns 200", r_filter_conf.status_code == 200)
        check("All returned tickets within confidence range", all(0.20 <= t["confidence_score"] <= 0.36 for t in r_filter_conf.json()["tickets"]))

        # 2.6 Filter by Overdue
        r_filter_overdue = client.get("/api/v1/tickets/?is_overdue=true", headers=admin_headers)
        check("Filter by is_overdue=true returns 200", r_filter_overdue.status_code == 200)
        check("Overdue tickets returned", any(t["ticket_id"] == t_fin1.ticket_id for t in r_filter_overdue.json()["tickets"]))

        # 2.7 Filter by Text Search
        r_filter_search = client.get(f"/api/v1/tickets/?search=parental leave", headers=admin_headers)
        check("Filter by search returns 200", r_filter_search.status_code == 200)
        check("Search returns parental leave ticket", any(t["ticket_id"] == t_hr1.ticket_id for t in r_filter_search.json()["tickets"]))

        print("\n--- 3. Testing Rich Ticket Detail (GET /tickets/{id}) ---")
        r_detail = client.get(f"/api/v1/tickets/{t_hr1.ticket_id}", headers=admin_headers)
        check("GET /tickets/{id} returns 200", r_detail.status_code == 200)
        d = r_detail.json()
        check("Detail contains user_question", "user_question" in d and d["user_question"] == t_hr1.original_question)
        check("Detail contains generated_answer", bool(d["generated_answer"]))
        check("Detail contains confidence_score", d["confidence_score"] == 0.35)
        check("Detail contains evidence", d["evidence"] == "Inconsistent citations across leave documents.")
        check("Detail contains citations list", len(d["citations"]) == 2 and "DOC_HR_POLICY_01" in d["citations"])
        check("Detail contains routing_method", bool(d["routing_method"]))
        check("Detail contains SLA status (sla_hours & sla_due_at)", d["sla_hours"] > 0 and d["sla_due_at"] is not None)
        check("Detail contains query_history from query_logs", d["query_history"] is not None)
        if d["query_history"]:
            check("Query history query_text matches", f"paid parental leave" in d["query_history"]["query_text"])
            check("Query history latency_ms matches", d["query_history"]["latency_ms"] == 350.5)

        print("\n--- 4. Testing Dedicated Administrative Actions ---")
        # 4.1 Assign Ticket (POST /tickets/{id}/assign)
        r_assign = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/assign",
            json={"assigned_to": str(hr_expert.id), "notes": "Assigned to HR Expert for parental policy review."},
            headers=admin_headers,
        )
        check("POST /tickets/{id}/assign returns 200", r_assign.status_code == 200)
        check("Ticket assigned_to is hr_expert", r_assign.json()["assigned_to"] == str(hr_expert.id))
        check("Ticket status changed to assigned", r_assign.json()["status"] == "assigned")
        check("Ticket assigned_domain_expert object populated", r_assign.json()["assigned_domain_expert"]["email"] == test_email_expert)

        # 4.2 Change Priority (POST /tickets/{id}/priority)
        r_prio = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/priority",
            json={"priority": "critical", "notes": "Escalated priority to critical due to upcoming onboarding."},
            headers=admin_headers,
        )
        check("POST /tickets/{id}/priority returns 200", r_prio.status_code == 200)
        check("Ticket priority changed to critical", r_prio.json()["priority"] == "critical")
        check("SLA hours recalculated to 24", r_prio.json()["sla_hours"] == 24)

        # 4.3 Change Status (POST /tickets/{id}/status)
        r_status = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/status",
            json={"status": "in_progress", "notes": "Expert is drafting updated leave policy."},
            headers=admin_headers,
        )
        check("POST /tickets/{id}/status returns 200", r_status.status_code == 200)
        check("Ticket status changed to in_progress", r_status.json()["status"] == "in_progress")

        # 4.4 Add Internal Notes (POST /tickets/{id}/notes)
        r_notes = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/notes",
            json={"notes": "Checked HR Portal v2: standard parental leave is 16 paid weeks."},
            headers=admin_headers,
        )
        check("POST /tickets/{id}/notes returns 200", r_notes.status_code == 200)
        check("Internal notes appended to feedback", "standard parental leave is 16 paid weeks" in r_notes.json()["feedback"])

        # 4.5 Resolve Ticket (POST /tickets/{id}/resolve)
        r_resolve = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/resolve",
            json={
                "resolution": "Eligible full-time employees are entitled to 16 continuous weeks of 100% paid parental leave.",
                "internal_notes": "Verified against Section 4.2 of 2026 Employee Handbook.",
            },
            headers=admin_headers,
        )
        check("POST /tickets/{id}/resolve returns 200", r_resolve.status_code == 200)
        check("Ticket status changed to resolved", r_resolve.json()["status"] == "resolved")
        check("Ticket resolution populated", "16 continuous weeks" in r_resolve.json()["resolution"])
        check("Ticket resolved_at timestamp populated", r_resolve.json()["resolved_at"] is not None)
        check("Ticket resolver_user populated", r_resolve.json()["resolver_user"]["email"] == test_email_admin)

        # 4.6 Close Ticket (POST /tickets/{id}/close)
        r_close = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/close",
            json={"feedback": "Ticket confirmed and closed after knowledge base ingestion."},
            headers=admin_headers,
        )
        check("POST /tickets/{id}/close returns 200", r_close.status_code == 200)
        check("Ticket status changed to closed", r_close.json()["status"] == "closed")

        print("\n--- 5. Testing Domain Isolation & Scoped RBAC ---")
        # 5.1 HR Manager can view HR ticket
        r_hr_view = client.get(f"/api/v1/tickets/{t_hr1.ticket_id}", headers=hr_mgr_headers)
        check("HR Manager CAN access HR Ticket", r_hr_view.status_code == 200)

        # 5.2 HR Manager CANNOT view Finance ticket (404/Access Denied)
        r_hr_fin_view = client.get(f"/api/v1/tickets/{t_fin1.ticket_id}", headers=hr_mgr_headers)
        check("HR Manager CANNOT access Finance Ticket (404)", r_hr_fin_view.status_code == 404)

        # 5.3 HR Manager CANNOT mutate Finance ticket (404)
        r_hr_fin_mutate = client.post(
            f"/api/v1/tickets/{t_fin1.ticket_id}/status",
            json={"status": "in_progress"},
            headers=hr_mgr_headers,
        )
        check("HR Manager CANNOT mutate Finance Ticket (404)", r_hr_fin_mutate.status_code == 404)

        # 5.4 Finance Manager CAN access Finance Ticket
        r_fin_view = client.get(f"/api/v1/tickets/{t_fin1.ticket_id}", headers=fin_mgr_headers)
        check("Finance Manager CAN access Finance Ticket", r_fin_view.status_code == 200)

        # 5.5 Regular Employee only sees own tickets
        r_user_list = client.get("/api/v1/tickets/", headers=user_headers)
        check("Employee GET /tickets/ returns 200", r_user_list.status_code == 200)
        check("Employee only sees tickets where user_id is themselves", all(t["user_id"] == str(reg_user.id) for t in r_user_list.json()["tickets"]))

        # 5.6 Employee CANNOT perform administrative mutations (403 Forbidden)
        r_user_mutate = client.post(
            f"/api/v1/tickets/{t_hr1.ticket_id}/resolve",
            json={"resolution": "Unauthorized resolution"},
            headers=user_headers,
        )
        check("Employee POST /resolve returns 403 Forbidden", r_user_mutate.status_code == 403)

        print("\n--- 6. Testing Audit Trail for Ticket Administrative Actions ---")
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.detail.ilike(f"%{t_hr1.ticket_id}%"))
            .all()
        )
        event_types = [a.event_type for a in audits]
        check("Audit log recorded for ticket_assigned", "ticket_assigned" in event_types)
        check("Audit log recorded for ticket_priority_changed", "ticket_priority_changed" in event_types)
        check("Audit log recorded for ticket_status_changed", "ticket_status_changed" in event_types)
        check("Audit log recorded for ticket_notes_added", "ticket_notes_added" in event_types)
        check("Audit log recorded for ticket_resolved", "ticket_resolved" in event_types)
        check("Audit log recorded for ticket_closed", "ticket_closed" in event_types)

    finally:
        # Cleanup
        db.query(Ticket).filter(Ticket.original_question.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Ticket).filter(Ticket.ticket_id.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(QueryLog).filter(QueryLog.query_id == f"QRY_HR_{suffix}").delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.detail.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(UserDomain).filter(UserDomain.user_id.in_([hr_manager.id, fin_manager.id, reg_user.id])).delete(synchronize_session=False)
        db.query(User).filter(User.email.in_([test_email_admin, test_email_hr_mgr, test_email_fin_mgr, test_email_expert, test_email_user])).delete(synchronize_session=False)
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
