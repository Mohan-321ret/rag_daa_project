"""
Phase 10: Automatic Ticketing from Low-Confidence Answers Test Suite
---------------------------------------------------------------------
Validates:
1. Dynamic threshold configuration by authorized administrators
2. RBAC protection on threshold configuration
3. Pipeline comparison: confidence_score < configured_threshold triggers ticket creation
4. Ticket model contains all 18 required fields
5. Safe user-facing notification without internal details leak
6. Deduplication on open low-confidence queries
7. Full ticket status lifecycle (OPEN, ROUTED, ASSIGNED, IN_PROGRESS, RESOLVED, CLOSED, REJECTED)
8. Role-scoped ticket listing and dashboard statistics
"""
import uuid
import sys

from fastapi.testclient import TestClient

from app.core.config import settings
settings.watch_enabled = False
settings.domain_routing_enabled = False

from app.db.base import init_db
from app.db.database import SessionLocal
from app.main import app
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import User
from app.models.system_setting import SystemSetting
from app.services.ticket_service import (
    create_ticket_from_low_confidence,
    get_ticket_confidence_threshold,
    update_ticketing_config,
)

init_db()

client = TestClient(app)
db = SessionLocal()
results = []


def check(name: str, condition: bool, extra: str = ""):
    results.append((name, condition, extra))
    status_str = "PASS" if condition else "FAIL"
    print(f"[{status_str}] {name} {extra}", flush=True)


def run_tests():
    # ── 0. Setup test users for RBAC ──────────────────────────────────────────
    suffix = uuid.uuid4().hex[:6]
    admin_email = f"admin-{suffix}@example.com"
    employee_email = f"employee-{suffix}@example.com"
    password = "SecurePassword123!"

    # Register admin
    client.post("/api/v1/auth/register", json={"email": admin_email, "password": password})
    db.query(User).filter(User.email == admin_email).update({"role": "super_admin"})
    db.commit()
    r_admin_login = client.post("/api/v1/auth/login", json={"email": admin_email, "password": password})
    admin_auth = {"Authorization": f"Bearer {r_admin_login.json()['access_token']}"}
    admin_user = db.query(User).filter(User.email == admin_email).first()

    # Register employee
    client.post("/api/v1/auth/register", json={"email": employee_email, "password": password})
    db.query(User).filter(User.email == employee_email).update({"role": "standard_employee"})
    db.commit()
    r_emp_login = client.post("/api/v1/auth/login", json={"email": employee_email, "password": password})
    emp_auth = {"Authorization": f"Bearer {r_emp_login.json()['access_token']}"}
    emp_user = db.query(User).filter(User.email == employee_email).first()

    # ── 1. Dynamic Threshold Configuration ─────────────────────────────────────
    print("\n--- 1. Testing Configurable Threshold ---")
    # Employee cannot update threshold (403)
    r_forbidden = client.patch(
        "/api/v1/tickets/config",
        json={"ticket_confidence_threshold": 0.70},
        headers=emp_auth,
    )
    check("Non-admin cannot update threshold (403 Forbidden)", r_forbidden.status_code == 403)

    # Admin updates threshold to 0.70
    r_update = client.patch(
        "/api/v1/tickets/config",
        json={"ticket_confidence_threshold": 0.70, "ticketing_enabled": True},
        headers=admin_auth,
    )
    check("Admin updates threshold to 0.70 (200 OK)", r_update.status_code == 200)
    check(
        "Threshold updated in response",
        r_update.json().get("ticket_confidence_threshold") == 0.70
        and r_update.json().get("threshold") == 0.70,
    )

    # Verify via GET /api/v1/tickets/config
    r_get_config = client.get("/api/v1/tickets/config", headers=emp_auth)
    check(
        "GET /tickets/config reflects active threshold",
        r_get_config.status_code == 200 and r_get_config.json().get("threshold") == 0.70,
    )

    # Verify service level dynamic lookup
    active_threshold = get_ticket_confidence_threshold(db)
    check("Service lookup returns DB threshold 0.70", active_threshold == 0.70)

    # ── 2. Pipeline Confidence Comparison & Ticket Generation ──────────────────
    print("\n--- 2. Testing Pipeline Comparison (confidence < threshold) ---")
    query_text = f"What is the company severance package policy? {suffix}"

    # Scenario A: High Confidence (0.85 >= 0.70) -> No ticket generated
    t_high, msg_high = create_ticket_from_low_confidence(
        db,
        query_id=f"QRY_HIGH_{suffix}",
        user_id=str(emp_user.id),
        original_question=query_text,
        generated_answer="The severance policy provides 2 weeks per year of service.",
        confidence_score=0.85,
    )
    check("High confidence (0.85 >= 0.70) creates NO ticket", t_high is None and msg_high is None)

    # Scenario B: Low Confidence (0.45 < 0.70) -> Ticket generated
    t_low, msg_low = create_ticket_from_low_confidence(
        db,
        query_id=f"QRY_LOW_{suffix}",
        user_id=str(emp_user.id),
        original_question=query_text,
        generated_answer="I believe the severance might be 10 weeks maybe.",
        confidence_score=0.45,
        evidence="Contradicting statements found across policy docs.",
        domain="HR",
    )
    check("Low confidence (0.45 < 0.70) creates ticket", t_low is not None and t_low.ticket_id.startswith("TKT_"))
    check(
        "Safe user message returned",
        msg_low is not None and "requires domain expert verification" in msg_low,
    )

    # ── 3. Ticket Model Fields Verification ────────────────────────────────────
    print("\n--- 3. Verifying All Required Ticket Model Fields ---")
    t_id = t_low.ticket_id
    ticket_row = db.query(Ticket).filter(Ticket.ticket_id == t_id).first()

    required_fields = [
        "ticket_id",
        "query_id",
        "user_id",
        "domain",
        "title",
        "description",
        "original_question",
        "generated_answer",
        "confidence_score",
        "threshold",
        "evidence",
        "priority",
        "status",
        "assigned_to",
        "created_at",
        "updated_at",
        "resolved_at",
        "resolution",
        "feedback",
    ]

    for f in required_fields:
        has_field = hasattr(ticket_row, f)
        check(f"Ticket has field: {f}", has_field)

    check("Ticket status is open", ticket_row.status in (TicketStatus.OPEN.value, "open", "OPEN"))
    check("Ticket priority is HIGH for 0.45 score", ticket_row.priority == TicketPriority.HIGH.value)
    check("Ticket threshold matches configured threshold 0.70", ticket_row.threshold == 0.70)

    # ── 4. Deduplication on Repeated Low-Confidence Queries ─────────────────────
    print("\n--- 4. Testing Deduplication ---")
    t_dup, msg_dup = create_ticket_from_low_confidence(
        db,
        query_id=f"QRY_DUP_{suffix}",
        user_id=str(emp_user.id),
        original_question=query_text.upper(),  # case-insensitive match
        generated_answer="Another uncertain answer.",
        confidence_score=0.35,  # lower confidence
    )
    check("Duplicate query returns same ticket", t_dup.ticket_id == t_id)
    check("Occurrence count incremented to 2", t_dup.occurrence_count == 2)
    check("Keeps lower confidence score 0.35", t_dup.confidence_score == 0.35)
    check("Recalculates priority to HIGH/CRITICAL", t_dup.priority in ("high", "critical"))

    # ── 5. Status Lifecycle Transitions ────────────────────────────────────────
    print("\n--- 5. Testing Status Lifecycle (OPEN -> ROUTED -> ASSIGNED -> IN_PROGRESS -> RESOLVED -> CLOSED) ---")
    # ROUTED
    r_route = client.patch(f"/api/v1/tickets/{t_id}", json={"status": "routed"}, headers=admin_auth)
    check("Transition to ROUTED (200 OK)", r_route.status_code == 200 and r_route.json()["status"] == "routed")

    # ASSIGNED
    assignee_id = str(admin_user.id)
    r_assign = client.patch(
        f"/api/v1/tickets/{t_id}",
        json={"status": "assigned", "assigned_to": assignee_id},
        headers=admin_auth,
    )
    check(
        "Transition to ASSIGNED with assignee (200 OK)",
        r_assign.status_code == 200
        and r_assign.json()["status"] == "assigned"
        and r_assign.json()["assigned_to"] == assignee_id,
    )

    # IN_PROGRESS
    r_prog = client.patch(f"/api/v1/tickets/{t_id}", json={"status": "in_progress"}, headers=admin_auth)
    check("Transition to IN_PROGRESS (200 OK)", r_prog.status_code == 200 and r_prog.json()["status"] == "in_progress")

    # RESOLVED
    r_resolve = client.patch(
        f"/api/v1/tickets/{t_id}",
        json={
            "status": "resolved",
            "resolution": "Confirmed HR policy Section 4.2: Severance is 2 weeks per year worked.",
            "feedback": "Updated knowledge base chunk for clarity.",
        },
        headers=admin_auth,
    )
    check(
        "Transition to RESOLVED with resolution and feedback (200 OK)",
        r_resolve.status_code == 200
        and r_resolve.json()["status"] == "resolved"
        and r_resolve.json()["resolved_at"] is not None
        and "Section 4.2" in r_resolve.json()["resolution"]
        and r_resolve.json()["feedback"] is not None,
    )

    # CLOSED
    r_close = client.patch(f"/api/v1/tickets/{t_id}", json={"status": "closed"}, headers=admin_auth)
    check("Transition to CLOSED (200 OK)", r_close.status_code == 200 and r_close.json()["status"] == "closed")

    # Test REJECTED status transition on a new ticket
    t_rej, _ = create_ticket_from_low_confidence(
        db,
        query_id=f"QRY_REJ_{suffix}",
        user_id=str(emp_user.id),
        original_question=f"Gibberish question {suffix}",
        generated_answer="Unclear",
        confidence_score=0.10,
    )
    r_rej = client.patch(
        f"/api/v1/tickets/{t_rej.ticket_id}",
        json={"status": "rejected", "resolution": "Not a valid business question"},
        headers=admin_auth,
    )
    check("Transition to REJECTED (200 OK)", r_rej.status_code == 200 and r_rej.json()["status"] == "rejected")

    # ── 6. Scoped Listing and Dashboard Stats ──────────────────────────────────
    print("\n--- 6. Testing Scoped Listing and Statistics ---")
    # Employee lists own tickets
    r_emp_list = client.get("/api/v1/tickets/", headers=emp_auth)
    check("Employee lists tickets (200 OK)", r_emp_list.status_code == 200)
    emp_tids = [x["ticket_id"] for x in r_emp_list.json()["tickets"]]
    check("Employee sees their created ticket", t_id in emp_tids)

    # Admin stats endpoint
    r_stats = client.get("/api/v1/tickets/stats", headers=admin_auth)
    check("Stats endpoint (200 OK)", r_stats.status_code == 200)
    stats = r_stats.json()
    check(
        "Stats contains all required status counts",
        "open" in stats
        and "routed" in stats
        and "assigned" in stats
        and "in_progress" in stats
        and "resolved" in stats
        and "closed" in stats
        and "rejected" in stats,
    )

    # ── Cleanup ───────────────────────────────────────────────────────────────
    db.query(Ticket).filter(Ticket.original_question.ilike(f"%{suffix}%")).delete(synchronize_session=False)
    db.query(SystemSetting).filter(SystemSetting.key == "ticket_confidence_threshold").delete(synchronize_session=False)
    db.query(User).filter(User.email.in_([admin_email, employee_email])).delete(synchronize_session=False)
    db.commit()
    db.close()

    print("\n==========================================")
    failed = [n for n, ok, extra in results if not ok]
    print(f"RESULTS: {len(results) - len(failed)} / {len(results)} PASSED")
    if failed:
        print(f"FAILED TESTS: {failed}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
