"""
RBAC Foundation test suite (real-DB TestClient, mirrors api_test.py style).

Covers the four categories the RBAC Foundation phase asks for:
  1. valid role access       - a role WITH the right permission succeeds
  2. invalid role access     - a role WITHOUT the right permission gets 403
  3. unauthorized API access - no token at all gets 401
  4. privilege escalation    - rank-ceiling + self-role-change guards hold

Test users are created via the real API (so bootstrap-role logic runs
normally), then their `role` column is overwritten directly in the DB —
that's fixture setup, not something under test, matching how tickets_test.py
seeds ticket rows directly.
"""
import time
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.ticket import Ticket

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]

results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str):
    email = f"rbac-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


owner = make_user("platform_owner", "owner")
superadmin = make_user("super_admin", "superadmin")
domain_mgr = make_user("domain_manager", "domainmgr")
analyst = make_user("analyst", "analyst")
employee = make_user("standard_employee", "employee")
client_user = make_user("client_user", "client")
guest = make_user("guest_user", "guest")

# ── /auth/me reports role ───────────────────────────────────────────────────
me = client.get("/api/v1/auth/me", headers=owner["headers"])
check("auth/me reports assigned role", me.status_code == 200 and me.json()["role"] == "platform_owner")

# ── 1. Valid role access ────────────────────────────────────────────────────
r = client.get("/api/v1/users/", headers=superadmin["headers"])
check("SUPER_ADMIN can list users (USER_READ)", r.status_code == 200, r.text[:100])

r = client.get("/api/v1/tickets/", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER can view tickets (TICKET_VIEW)", r.status_code == 200, r.text[:100])

r = client.get("/api/v1/llm/models", headers=analyst["headers"])
check("ANALYST can view LLM models (LLM_VIEW)", r.status_code == 200, r.text[:100])

doc_id = None
try:
    content = f"RBAC test document {suffix}. Unique marker to avoid dedup collisions."
    r = client.post(
        "/api/v1/documents/upload",
        files={"file": (f"rbac_{suffix}.txt", content, "text/plain")},
        # visibility=global: domain is mandatory for domain/restricted visibility
        # (Domain-Aware Document Metadata phase) — this test only cares about the
        # DOCUMENT_UPLOAD permission gate, not domain scoping (see document_metadata_test.py).
        data={"visibility": "global"},
        headers=analyst["headers"],
    )
    # Upload is now an async job (Admin Panel: Data Injection Management) —
    # 202 + job_id immediately, poll for the resulting document_id.
    check("ANALYST can upload a document (DOCUMENT_UPLOAD)", r.status_code == 202, r.text[:200])
    job_id = r.json().get("job_id")
    deadline = time.time() + 30
    job = {}
    while job_id and time.time() < deadline:
        job = client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=analyst["headers"]).json()
        if job.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    doc_id = job.get("document_id")
except Exception as exc:
    check("ANALYST can upload a document (DOCUMENT_UPLOAD)", False, str(exc))

# ── 2. Invalid role access ──────────────────────────────────────────────────
r = client.post(
    "/api/v1/documents/upload",
    files={"file": ("nope.txt", "guest cannot upload this", "text/plain")},
    headers=guest["headers"],
)
check("GUEST_USER cannot upload (no DOCUMENT_UPLOAD)", r.status_code == 403, r.text[:100])

r = client.get("/api/v1/users/", headers=client_user["headers"])
check("CLIENT_USER cannot list users (no USER_READ)", r.status_code == 403, r.text[:100])

r = client.patch(f"/api/v1/tickets/TKT_NONEXISTENT", json={"status": "resolved"}, headers=employee["headers"])
check("STANDARD_EMPLOYEE cannot resolve tickets (no TICKET_RESOLVE) -> 403 before 404", r.status_code == 403, r.text[:100])

r = client.get("/api/v1/feedback/metrics/summary", headers=guest["headers"])
check("GUEST_USER cannot view analytics (no ANALYTICS_VIEW)", r.status_code == 403, r.text[:100])

# ── 3. Unauthorized API access (no token) ───────────────────────────────────
r = client.get("/api/v1/tickets/")
check("No token on GET /tickets -> 401", r.status_code == 401, r.text[:100])

r = client.post("/api/v1/documents/upload", files={"file": ("x.txt", "hi", "text/plain")})
check("No token on POST /documents/upload -> 401", r.status_code == 401, r.text[:100])

r = client.post("/api/v1/rag/query", json={"question": "test"})
check("No token on POST /rag/query -> 401", r.status_code == 401, r.text[:100])

# Malformed/unrecognized role string -> fail closed (403, not 500)
ghost_email = f"rbac-ghost-{suffix}@example.com"
gr = client.post("/api/v1/auth/register", json={"email": ghost_email, "password": "testpass123"})
db.query(User).filter(User.id == gr.json()["user"]["id"]).update({"role": "not_a_real_role"})
db.commit()
ghost_login = client.post("/api/v1/auth/login", json={"email": ghost_email, "password": "testpass123"})
r = client.get("/api/v1/tickets/", headers={"Authorization": f"Bearer {ghost_login.json()['access_token']}"})
check("Unrecognized role fails closed -> 403 (not 500)", r.status_code == 403, r.text[:100])

# ── 4. Privilege escalation attempts ────────────────────────────────────────

# 4a. ANALYST holds no ROLE_ASSIGN at all.
# (DOMAIN_MANAGER now legitimately holds ROLE_ASSIGN as of the User/Domain/
# Access Management phase — scoped to users sharing its domain, see
# admin_panel_test.py for that coverage. This check needs a role that still
# has none of it, at any scope.)
r = client.patch(f"/api/v1/users/{employee['id']}", json={"role": "analyst"}, headers=analyst["headers"])
check("ANALYST cannot assign roles at all (no ROLE_ASSIGN)", r.status_code == 403, r.text[:150])

# 4b. SUPER_ADMIN (rank 5) cannot assign PLATFORM_OWNER (rank 6) - above its own rank.
r = client.patch(f"/api/v1/users/{employee['id']}", json={"role": "platform_owner"}, headers=superadmin["headers"])
check("SUPER_ADMIN cannot assign a role above its own rank", r.status_code == 403, r.text[:150])

# 4c. No one can change their OWN role, even PLATFORM_OWNER on itself.
r = client.patch(f"/api/v1/users/{owner['id']}", json={"role": "super_admin"}, headers=owner["headers"])
check("Cannot change own role (self-escalation guard)", r.status_code == 403, r.text[:150])

r = client.patch(f"/api/v1/users/{superadmin['id']}", json={"role": "guest_user"}, headers=superadmin["headers"])
check("Cannot change own role even to downgrade self", r.status_code == 403, r.text[:150])

# 4d. Valid contrast case: PLATFORM_OWNER CAN assign SUPER_ADMIN (rank below own) to someone else.
r = client.patch(f"/api/v1/users/{employee['id']}", json={"role": "super_admin"}, headers=owner["headers"])
check("PLATFORM_OWNER can assign a role below its own rank", r.status_code == 200, r.text[:150])
check("...and the target's role actually changed", r.status_code == 200 and r.json().get("role") == "super_admin")

# 4e. Valid contrast case: PLATFORM_OWNER CAN assign an EQUAL rank (PLATFORM_OWNER) to someone else.
r = client.patch(f"/api/v1/users/{client_user['id']}", json={"role": "platform_owner"}, headers=owner["headers"])
check("PLATFORM_OWNER can assign an equal-rank role to someone else", r.status_code == 200, r.text[:150])

# 4f. SUPER_ADMIN CAN assign a role at its own rank ceiling (another SUPER_ADMIN) to someone else.
r = client.patch(f"/api/v1/users/{guest['id']}", json={"role": "super_admin"}, headers=superadmin["headers"])
check("SUPER_ADMIN can assign a role at its own rank", r.status_code == 200, r.text[:150])

# ── Resource-level scoping: ticket ownership (role-level + resource-level combined) ─
# Fresh user, NOT `employee` — the escalation section above mutated
# `employee`'s role to super_admin, which would make it a reviewer and
# defeat this test.
emp2 = make_user("standard_employee", "employee2")

from app.models.domain import Domain
from app.models.user_domain import UserDomain

# Scoping the tickets to a domain that domain_mgr manages
dom = db.query(Domain).first()
if dom:
    db.add(UserDomain(user_id=domain_mgr["id"], domain_id=dom.id, is_primary=True))
    db.commit()
    t1 = Ticket(
        ticket_id=f"TKT_RBAC1_{suffix}", raised_by_user_id=emp2["id"], query_text="employee's own query",
        confidence_score=0.2, department="General", routed_domain_id=dom.id, domain=dom.name,
    )
    t2 = Ticket(
        ticket_id=f"TKT_RBAC2_{suffix}", raised_by_user_id=analyst["id"], query_text="someone else's query",
        confidence_score=0.2, department="General", routed_domain_id=dom.id, domain=dom.name,
    )
else:
    t1 = Ticket(
        ticket_id=f"TKT_RBAC1_{suffix}", raised_by_user_id=emp2["id"], query_text="employee's own query",
        confidence_score=0.2, department="General",
    )
    t2 = Ticket(
        ticket_id=f"TKT_RBAC2_{suffix}", raised_by_user_id=analyst["id"], query_text="someone else's query",
        confidence_score=0.2, department="General",
    )

db.add_all([t1, t2])
db.commit()

r = client.get("/api/v1/tickets/", params={"limit": 200}, headers=emp2["headers"])
seen_ids = {t["ticket_id"] for t in r.json()["tickets"]}
check("Non-reviewer (STANDARD_EMPLOYEE) sees own ticket", t1.ticket_id in seen_ids)
check("Non-reviewer (STANDARD_EMPLOYEE) does NOT see others' tickets", t2.ticket_id not in seen_ids)

r = client.get(f"/api/v1/tickets/{t2.ticket_id}", headers=emp2["headers"])
check("Non-reviewer GET on someone else's ticket -> 404 (not 403, avoids confirming existence)", r.status_code == 404)

r = client.get("/api/v1/tickets/", params={"limit": 200}, headers=domain_mgr["headers"])
seen_ids = {t["ticket_id"] for t in r.json()["tickets"]}
check("Reviewer (DOMAIN_MANAGER) sees ALL tickets regardless of owner",
      t1.ticket_id in seen_ids and t2.ticket_id in seen_ids)

# ── Cleanup ──────────────────────────────────────────────────────────────────
db.query(Ticket).filter(Ticket.ticket_id.in_([t1.ticket_id, t2.ticket_id])).delete(synchronize_session=False)
if doc_id:
    db.query(Chunk).filter(Chunk.document_id == doc_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.document_id == doc_id).delete(synchronize_session=False)
# Clean up user domains
all_user_emails = [f"rbac-{tag}-{suffix}@example.com" for tag in ("owner", "superadmin", "domainmgr", "analyst", "employee", "client", "guest", "employee2", "ghost")]
test_users = db.query(User).filter(User.email.in_(all_user_emails)).all()
test_user_ids = [u.id for u in test_users]
if test_user_ids:
    db.query(UserDomain).filter(UserDomain.user_id.in_(test_user_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"rbac-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
