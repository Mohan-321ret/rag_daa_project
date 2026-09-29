"""
Phase 2.4 Ticket Management API Test Suite
-------------------------------------------
Validates REST APIs for the ticketing system according to FastAPI architecture,
authentication patterns, authorization rules, domain scoping, and error responses.

Required APIs Tested:
1. POST /api/tickets (Create ticket)
2. GET /api/tickets/my (Get current user's tickets)
3. GET /api/tickets/manager (Get tickets assigned to current Domain Manager)
4. GET /api/tickets/{ticket_id} (Get ticket details)
5. PUT /api/tickets/{ticket_id}/status (Update ticket status)
6. PUT /api/tickets/{ticket_id}/assign (Assign/reassign ticket)
7. POST /api/tickets/{ticket_id}/resolve (Resolve ticket with text)
"""
import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.domain import Domain
from app.models.ticket import Ticket, TicketStatus, TicketPriority
from app.models.user import User
from app.models.user_domain import UserDomain

init_db()

client = TestClient(app)
db: Session = SessionLocal()

results = []

def check(name: str, cond: bool, extra: str = ""):
    results.append((name, cond, extra))
    status_str = "PASS" if cond else "FAIL"
    print(f"[{status_str}] {name} {extra}")
    assert cond, f"Check failed: {name} - {extra}"


def setup_test_users_and_domains():
    """Create test domain structure and users for Phase 2.4 validation."""
    suffix = uuid.uuid4().hex[:6]
    
    # 1. Create HR & Finance domains
    hr_domain = Domain(
        key=f"hr_{suffix}",
        name=f"HR Department {suffix}",
        description="Human Resources Domain"
    )
    fin_domain = Domain(
        key=f"finance_{suffix}",
        name=f"Finance Department {suffix}",
        description="Finance & Accounting Domain"
    )
    db.add(hr_domain)
    db.add(fin_domain)
    db.commit()
    db.refresh(hr_domain)
    db.refresh(fin_domain)

    # Helper to register & login
    def _create_user(email: str, role: str) -> dict:
        client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        db.commit()
        db.refresh(user)
        login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"})
        token = login_resp.json()["access_token"]
        return {"user": user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}

    emp1 = _create_user(f"emp1_{suffix}@example.com", "standard_employee")
    emp2 = _create_user(f"emp2_{suffix}@example.com", "standard_employee")
    hr_mgr = _create_user(f"hrmgr_{suffix}@example.com", "domain_manager")
    fin_mgr = _create_user(f"finmgr_{suffix}@example.com", "domain_manager")

    # Link HR manager to HR domain, Finance manager to Finance domain
    db.add(UserDomain(user_id=hr_mgr["user"].id, domain_id=hr_domain.id))
    db.add(UserDomain(user_id=fin_mgr["user"].id, domain_id=fin_domain.id))
    db.commit()

    return {
        "suffix": suffix,
        "hr_domain": hr_domain,
        "fin_domain": fin_domain,
        "emp1": emp1,
        "emp2": emp2,
        "hr_mgr": hr_mgr,
        "fin_mgr": fin_mgr,
    }


def run_tests():
    data = setup_test_users_and_domains()
    emp1 = data["emp1"]
    emp2 = data["emp2"]
    hr_mgr = data["hr_mgr"]
    fin_mgr = data["fin_mgr"]
    hr_domain = data["hr_domain"]
    fin_domain = data["fin_domain"]
    suffix = data["suffix"]

    print("\n--- 1. Testing Unauthenticated Access (401 Unauthorized) ---")
    r_unauth = client.get("/api/tickets/my")
    check("Unauthenticated GET /api/tickets/my returns 401", r_unauth.status_code == 401)
    
    r_unauth_create = client.post("/api/tickets", json={"title": "Test", "description": "Test"})
    check("Unauthenticated POST /api/tickets returns 401", r_unauth_create.status_code == 401)

    print("\n--- 2. Testing API 1: Create Ticket (POST /api/tickets) ---")
    # 2.1 Valid creation by Employee 1
    create_payload = {
        "title": f"Leave Balance Discrepancy {suffix}",
        "description": "My annual leave balance is showing 10 days instead of 15 days.",
        "original_question": "What is my annual leave entitlement?",
        "generated_answer": "Standard annual leave entitlement is 15 days per year.",
        "confidence_score": 0.35,
        "priority": "high",
        "domain": hr_domain.key,
    }
    r_create = client.post("/api/tickets", json=create_payload, headers=emp1["headers"])
    check("POST /api/tickets returns 201 Created", r_create.status_code == 201, r_create.text)
    ticket1_data = r_create.json()
    t1_id = ticket1_data["ticket_id"]
    check("Ticket ID starts with TKT_", t1_id.startswith("TKT_"))
    check("Ticket title matches", ticket1_data["title"] == create_payload["title"])

    # Also test /api/v1/tickets alias
    r_create_v1 = client.post("/api/v1/tickets/", json={
        "title": f"Tax Exemption Query {suffix}",
        "description": "How do I claim Section 80C tax exemption?",
        "original_question": "How to submit 80C proof?",
        "generated_answer": "Submit tax proofs in the portal before March 15.",
        "confidence_score": 0.40,
        "priority": "medium",
        "domain": fin_domain.key,
    }, headers=emp2["headers"])
    check("POST /api/v1/tickets/ returns 201 Created", r_create_v1.status_code == 201)
    ticket2_data = r_create_v1.json()
    t2_id = ticket2_data["ticket_id"]

    # 2.2 Validation failures on creation
    r_bad_payload = client.post("/api/tickets", json={
        "title": "Incomplete Payload",
        # missing description, original_question, generated_answer, confidence_score
    }, headers=emp1["headers"])
    check("POST /api/tickets with missing fields returns 422", r_bad_payload.status_code == 422)

    r_bad_prio = client.post("/api/tickets", json={
        "title": "Invalid Priority",
        "description": "Test description",
        "original_question": "Test question",
        "generated_answer": "Test answer",
        "confidence_score": 0.5,
        "priority": "ultra_high_invalid",
    }, headers=emp1["headers"])
    check("POST /api/tickets with invalid priority returns 422", r_bad_prio.status_code == 422)

    print("\n--- 3. Testing API 2: Get Current User's Tickets (GET /api/tickets/my) ---")
    r_my1 = client.get("/api/tickets/my", headers=emp1["headers"])
    check("Employee 1 GET /api/tickets/my returns 200", r_my1.status_code == 200)
    emp1_tickets = r_my1.json()["tickets"]
    check("Employee 1 sees ticket 1", any(t["ticket_id"] == t1_id for t in emp1_tickets))
    check("Employee 1 DOES NOT see Employee 2's ticket 2", not any(t["ticket_id"] == t2_id for t in emp1_tickets))

    r_my2 = client.get("/api/tickets/my", headers=emp2["headers"])
    check("Employee 2 GET /api/tickets/my returns 200", r_my2.status_code == 200)
    emp2_tickets = r_my2.json()["tickets"]
    check("Employee 2 sees ticket 2", any(t["ticket_id"] == t2_id for t in emp2_tickets))
    check("Employee 2 DOES NOT see Employee 1's ticket 1", not any(t["ticket_id"] == t1_id for t in emp2_tickets))

    print("\n--- 4. Testing API 3: Get Domain Manager Tickets (GET /api/tickets/manager) ---")
    # 4.1 Standard Employee access forbidden
    r_mgr_forbidden = client.get("/api/tickets/manager", headers=emp1["headers"])
    check("Standard Employee GET /api/tickets/manager returns 403", r_mgr_forbidden.status_code == 403)

    # 4.2 HR Manager sees HR domain ticket 1, but NOT Finance domain ticket 2
    r_hr_mgr = client.get("/api/tickets/manager", headers=hr_mgr["headers"])
    check("HR Manager GET /api/tickets/manager returns 200", r_hr_mgr.status_code == 200)
    hr_mgr_tickets = r_hr_mgr.json()["tickets"]
    check("HR Manager sees HR domain ticket 1", any(t["ticket_id"] == t1_id for t in hr_mgr_tickets))
    check("HR Manager DOES NOT see Finance domain ticket 2", not any(t["ticket_id"] == t2_id for t in hr_mgr_tickets))

    # 4.3 Finance Manager sees Finance domain ticket 2, but NOT HR domain ticket 1
    r_fin_mgr = client.get("/api/tickets/manager", headers=fin_mgr["headers"])
    check("Finance Manager GET /api/tickets/manager returns 200", r_fin_mgr.status_code == 200)
    fin_mgr_tickets = r_fin_mgr.json()["tickets"]
    check("Finance Manager sees Finance domain ticket 2", any(t["ticket_id"] == t2_id for t in fin_mgr_tickets))
    check("Finance Manager DOES NOT see HR domain ticket 1", not any(t["ticket_id"] == t1_id for t in fin_mgr_tickets))

    print("\n--- 5. Testing API 4: Get Ticket Details (GET /api/tickets/{ticket_id}) ---")
    # 5.1 Owner can view their own ticket
    r_detail_owner = client.get(f"/api/tickets/{t1_id}", headers=emp1["headers"])
    check("Owner GET /api/tickets/{ticket_id} returns 200", r_detail_owner.status_code == 200)
    check("Ticket detail contains original_question", r_detail_owner.json()["original_question"] == create_payload["original_question"])

    # 5.2 Non-owner employee gets 404 (data protection: do not leak other user's ticket)
    r_detail_other_emp = client.get(f"/api/tickets/{t1_id}", headers=emp2["headers"])
    check("Non-owner employee GET /api/tickets/{other_ticket} returns 404", r_detail_other_emp.status_code == 404)

    # 5.3 HR Manager can view HR ticket
    r_detail_hr_mgr = client.get(f"/api/tickets/{t1_id}", headers=hr_mgr["headers"])
    check("Authorized Domain Manager GET /api/tickets/{ticket_id} returns 200", r_detail_hr_mgr.status_code == 200)

    # 5.4 Finance Manager CANNOT view HR ticket (returns 404)
    r_detail_fin_mgr_on_hr = client.get(f"/api/tickets/{t1_id}", headers=fin_mgr["headers"])
    check("Unauthorized Domain Manager GET /api/tickets/{other_domain_ticket} returns 404", r_detail_fin_mgr_on_hr.status_code == 404)

    # 5.5 Non-existent ticket ID
    r_detail_404 = client.get("/api/tickets/TKT_NONEXISTENT_9999", headers=hr_mgr["headers"])
    check("Non-existent ticket ID GET returns 404", r_detail_404.status_code == 404)

    print("\n--- 6. Testing API 5: Update Ticket Status (PUT /api/tickets/{ticket_id}/status) ---")
    # 6.1 Standard employee forbidden from changing ticket status
    r_status_emp = client.put(f"/api/tickets/{t1_id}/status", json={"status": "in_progress"}, headers=emp1["headers"])
    check("Standard employee PUT /status returns 403 Forbidden", r_status_emp.status_code == 403)

    # 6.2 HR Manager updates HR ticket status to in_progress
    r_status_mgr = client.put(f"/api/tickets/{t1_id}/status", json={"status": "in_progress", "notes": "Beginning review"}, headers=hr_mgr["headers"])
    check("Authorized Manager PUT /status returns 200", r_status_mgr.status_code == 200)
    check("Status updated to in_progress", r_status_mgr.json()["status"] == "in_progress")

    # 6.3 Invalid status value
    r_status_invalid = client.put(f"/api/tickets/{t1_id}/status", json={"status": "invalid_status_xyz"}, headers=hr_mgr["headers"])
    check("PUT /status with invalid status returns 422", r_status_invalid.status_code == 422)

    # 6.4 Unauthorized manager updating another domain's ticket
    r_status_unauth_mgr = client.put(f"/api/tickets/{t1_id}/status", json={"status": "in_progress"}, headers=fin_mgr["headers"])
    check("Unauthorized Manager PUT /status returns 404", r_status_unauth_mgr.status_code == 404)

    print("\n--- 7. Testing API 6: Assign / Reassign Ticket (PUT /api/tickets/{ticket_id}/assign) ---")
    # 7.1 Standard employee forbidden from assigning tickets
    r_assign_emp = client.put(f"/api/tickets/{t1_id}/assign", json={"assigned_to": str(hr_mgr["user"].id)}, headers=emp1["headers"])
    check("Standard employee PUT /assign returns 403 Forbidden", r_assign_emp.status_code == 403)

    # 7.2 HR Manager assigns HR ticket to HR Manager by email
    r_assign_ok = client.put(f"/api/tickets/{t1_id}/assign", json={
        "assigned_to": hr_mgr["user"].email,
        "notes": "Assigning to HR lead for investigation"
    }, headers=hr_mgr["headers"])
    check("HR Manager PUT /assign with email returns 200", r_assign_ok.status_code == 200)
    check("Assigned_to updated to user UUID", r_assign_ok.json()["assigned_to"] == str(hr_mgr["user"].id))

    # 7.3 Assign to non-existent user returns 400 Bad Request
    r_assign_bad_user = client.put(f"/api/tickets/{t1_id}/assign", json={"assigned_to": "nonexistent_user@example.com"}, headers=hr_mgr["headers"])
    check("PUT /assign to non-existent user returns 400 Bad Request", r_assign_bad_user.status_code == 400)

    # 7.4 Unauthorized manager assigning ticket outside domain returns 404
    r_assign_unauth_mgr = client.put(f"/api/tickets/{t1_id}/assign", json={"assigned_to": str(fin_mgr["user"].id)}, headers=fin_mgr["headers"])
    check("Unauthorized Manager PUT /assign returns 404", r_assign_unauth_mgr.status_code == 404)

    print("\n--- 8. Testing API 7: Resolve Ticket (POST /api/tickets/{ticket_id}/resolve) ---")
    # 8.1 Standard employee forbidden from resolving tickets
    r_resolve_emp = client.post(f"/api/tickets/{t1_id}/resolve", json={"resolution": "Resolved by employee"}, headers=emp1["headers"])
    check("Standard employee POST /resolve returns 403 Forbidden", r_resolve_emp.status_code == 403)

    # 8.2 Validation failure: empty / short resolution text
    r_resolve_short = client.post(f"/api/tickets/{t1_id}/resolve", json={"resolution": "a"}, headers=hr_mgr["headers"])
    check("POST /resolve with short resolution text returns 422", r_resolve_short.status_code == 422)

    # 8.3 HR Manager resolves HR ticket with valid resolution
    resolution_text = "Verified employee policy. Annual leave entitlement for standard full-time employees is 15 days."
    r_resolve_ok = client.post(f"/api/tickets/{t1_id}/resolve", json={
        "resolution": resolution_text,
        "resolution_type": "KNOWLEDGE_MISSING",
        "internal_notes": "Policy document section 4.2 confirmed.",
    }, headers=hr_mgr["headers"])
    check("Authorized Manager POST /resolve returns 200", r_resolve_ok.status_code == 200, r_resolve_ok.text)
    resolved_ticket = r_resolve_ok.json()
    check("Ticket status is resolved", resolved_ticket["status"] == "resolved")
    check("Resolution text recorded", resolved_ticket["resolution"] == resolution_text)
    check("Resolved_at timestamp present", resolved_ticket["resolved_at"] is not None)

    # 8.4 Unauthorized manager resolving ticket in another domain returns 404
    r_resolve_unauth_mgr = client.post(f"/api/tickets/{t2_id}/resolve", json={"resolution": "Cross-domain resolution attempt"}, headers=hr_mgr["headers"])
    check("Unauthorized Manager POST /resolve on other domain ticket returns 404", r_resolve_unauth_mgr.status_code == 404)

    print("\n--- Cleanup Test Data ---")
    try:
        db.query(Ticket).filter(Ticket.title.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(UserDomain).filter(UserDomain.user_id.in_([emp1["user"].id, emp2["user"].id, hr_mgr["user"].id, fin_mgr["user"].id])).delete(synchronize_session=False)
        db.query(User).filter(User.email.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.query(Domain).filter(Domain.key.ilike(f"%{suffix}%")).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        print("Cleanup error:", e)
    finally:
        db.close()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n==========================================")
    print(f"RESULTS: {len(results) - len(failed)} / {len(results)} PASSED")
    if failed:
        print(f"FAILED CHECKS ({len(failed)}):")
        for f in failed:
            print(f" - {f}")
        raise SystemExit(1)
    else:
        print("ALL PHASE 2.4 TICKET API TESTS PASSED!")


if __name__ == "__main__":
    run_tests()
