"""
User, Domain & Access Management test suite (real-DB TestClient).

Covers what rbac_test.py / access_matrix_test.py don't: domain CRUD, admin
user creation, list/search/filtering, domain-scoped Domain Manager
authority (list/get/update restricted to shared domains), the new
rank-modify guard ("lower-level roles cannot modify higher-level
administrators" — independent of can_assign_role, which only bounds the
role being ASSIGNED), domain-assignment scope guards, audit logging, and
last_login tracking.
"""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.domain import Domain
from app.models.user_domain import UserDomain
from app.models.audit_log import AuditLog

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str, domain_ids=None):
    email = f"apm-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    if domain_ids:
        db.query(UserDomain).filter(UserDomain.user_id == user_id).delete()
        for i, did in enumerate(domain_ids):
            db.add(UserDomain(user_id=user_id, domain_id=did, is_primary=(i == 0)))
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


# ── Fetch seeded domain ids ─────────────────────────────────────────────────
hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
assert hr and finance, "Phase 3 seed domains (hr, finance) missing — did init_db() run?"
HR_ID, FINANCE_ID = str(hr.id), str(finance.id)

owner = make_user("platform_owner", "owner")
superadmin = make_user("super_admin", "superadmin")
hr_manager = make_user("domain_manager", "hrmanager", domain_ids=[HR_ID])
no_domain_manager = make_user("domain_manager", "nodomainmanager")  # zero domains -> fail closed
hr_employee = make_user("standard_employee", "hremployee", domain_ids=[HR_ID])
finance_employee = make_user("standard_employee", "financeemployee", domain_ids=[FINANCE_ID])
client_user = make_user("client_user", "client")

# ── Domain CRUD ──────────────────────────────────────────────────────────────
r = client.get("/api/v1/domains/", headers=client_user["headers"])
check("any authenticated user can list domains", r.status_code == 200)
keys = {d["key"] for d in r.json()["domains"]}
check("seeded domains present", {"hr", "finance", "it", "legal", "sales", "operations", "engineering"} <= keys)

r = client.post("/api/v1/domains/", json={"key": f"axm-{suffix}", "name": "AXM Test Domain"}, headers=client_user["headers"])
check("CLIENT_USER cannot create a domain (no DOMAIN_MANAGE)", r.status_code == 403)

r = client.post("/api/v1/domains/", json={"key": f"axm-{suffix}", "name": "AXM Test Domain"}, headers=owner["headers"])
check("PLATFORM_OWNER can create a domain", r.status_code == 201)
new_domain_id = r.json()["id"]

r = client.post("/api/v1/domains/", json={"key": f"axm-{suffix}", "name": "Duplicate"}, headers=owner["headers"])
check("duplicate domain key -> 409", r.status_code == 409)

r = client.patch(f"/api/v1/domains/{new_domain_id}", json={"name": "Renamed"}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER cannot manage domain entities (no DOMAIN_MANAGE)", r.status_code == 403)

r = client.patch(f"/api/v1/domains/{new_domain_id}", json={"name": "Renamed", "is_active": False}, headers=owner["headers"])
check("PLATFORM_OWNER can rename/deactivate a domain", r.status_code == 200 and r.json()["name"] == "Renamed")

# ── Admin user creation (USER_CREATE) ───────────────────────────────────────
new_email = f"apm-created-{suffix}@example.com"
r = client.post("/api/v1/users/", json={
    "email": new_email, "password": "testpass123", "full_name": "Created By Owner",
    "role": "domain_manager", "domain_ids": [HR_ID],
}, headers=owner["headers"])
check("PLATFORM_OWNER can create a user with role+domain", r.status_code == 201, r.text[:150])
check("...created user has the assigned domain", r.status_code == 201 and any(d["key"] == "hr" for d in r.json().get("domains", [])))
created_user_id = r.json()["id"] if r.status_code == 201 else None

r = client.post("/api/v1/users/", json={"email": new_email, "password": "testpass123", "role": "guest_user"}, headers=owner["headers"])
check("duplicate email on create -> 409", r.status_code == 409)

r = client.post("/api/v1/users/", json={
    "email": f"apm-x-{suffix}@example.com", "password": "testpass123", "role": "guest_user",
    "domain_ids": ["00000000-0000-0000-0000-000000000000"],
}, headers=owner["headers"])
check("unknown domain_id on create -> 422", r.status_code == 422)

r = client.post("/api/v1/users/", json={
    "email": f"apm-y-{suffix}@example.com", "password": "testpass123", "role": "super_admin",
}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER cannot create a SUPER_ADMIN (rank ceiling)", r.status_code == 403)

r = client.post("/api/v1/users/", json={
    "email": f"apm-z-{suffix}@example.com", "password": "testpass123", "role": "standard_employee",
    "domain_ids": [HR_ID],
}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER can create a user within their own domain", r.status_code == 201, r.text[:150])

r = client.post("/api/v1/users/", json={
    "email": f"apm-w-{suffix}@example.com", "password": "testpass123", "role": "standard_employee",
    "domain_ids": [FINANCE_ID],
}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER cannot create a user in a domain they don't manage", r.status_code == 403)

r = client.post("/api/v1/users/", json={"email": f"apm-v-{suffix}@example.com", "password": "testpass123"}, headers=client_user["headers"])
check("CLIENT_USER cannot create users (no USER_CREATE)", r.status_code == 403)

# ── List / search / filter ──────────────────────────────────────────────────
r = client.get("/api/v1/users/", params={"role": "domain_manager", "limit": 200}, headers=owner["headers"])
check("PLATFORM_OWNER can filter by role", r.status_code == 200 and all(u["role"] == "domain_manager" for u in r.json()["users"]))

r = client.get("/api/v1/users/", params={"domain_id": HR_ID, "limit": 200}, headers=owner["headers"])
hr_ids_seen = {u["id"] for u in r.json()["users"]}
check("PLATFORM_OWNER can filter by domain_id", r.status_code == 200 and hr_employee["id"] in hr_ids_seen and finance_employee["id"] not in hr_ids_seen)

r = client.get("/api/v1/users/", params={"q": f"apm-hremployee-{suffix}"}, headers=owner["headers"])
check("search by email substring", r.status_code == 200 and any(u["id"] == hr_employee["id"] for u in r.json()["users"]))

r = client.get("/api/v1/users/", params={"limit": 200}, headers=hr_manager["headers"])
seen = {u["id"] for u in r.json()["users"]}
check("DOMAIN_MANAGER (hr) sees hr-domain users", hr_employee["id"] in seen)
check("DOMAIN_MANAGER (hr) does NOT see finance-only users", finance_employee["id"] not in seen)

r = client.get("/api/v1/users/", headers=no_domain_manager["headers"])
check("DOMAIN_MANAGER with zero domains sees nobody (fail closed)", r.status_code == 200 and r.json()["total"] == 0)

# ── Get single user: domain scoping ─────────────────────────────────────────
r = client.get(f"/api/v1/users/{hr_employee['id']}", headers=hr_manager["headers"])
check("DOMAIN_MANAGER (hr) can view an hr-domain user", r.status_code == 200)
r = client.get(f"/api/v1/users/{finance_employee['id']}", headers=hr_manager["headers"])
check("DOMAIN_MANAGER (hr) cannot view a finance-only user -> 404", r.status_code == 404)
r = client.get(f"/api/v1/users/{finance_employee['id']}", headers=superadmin["headers"])
check("SUPER_ADMIN can view any user regardless of domain", r.status_code == 200)

# ── Update: domain scoping + rank guard + domain-assignment scope ──────────
r = client.patch(f"/api/v1/users/{finance_employee['id']}", json={"full_name": "Nope"}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER (hr) cannot edit a finance-only user -> 404", r.status_code == 404)

r = client.patch(f"/api/v1/users/{hr_employee['id']}", json={"full_name": "HR Employee Renamed"}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER (hr) can edit an hr-domain user", r.status_code == 200 and r.json()["full_name"] == "HR Employee Renamed")

r = client.patch(f"/api/v1/users/{hr_employee['id']}", json={"role": "super_admin"}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER cannot promote within-domain user to SUPER_ADMIN (rank ceiling)", r.status_code == 403)

r = client.patch(f"/api/v1/users/{hr_employee['id']}", json={"role": "analyst"}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER can promote within-domain user to a lower-ranked role", r.status_code == 200 and r.json()["role"] == "analyst")

# The key new rule: rank-modify guard applies to ALL fields, not just role,
# and applies regardless of domain scoping — SUPER_ADMIN outranked by PLATFORM_OWNER.
r = client.patch(f"/api/v1/users/{owner['id']}", json={"is_active": False}, headers=superadmin["headers"])
check("SUPER_ADMIN cannot deactivate a PLATFORM_OWNER (rank-modify guard)", r.status_code == 403)
r = client.patch(f"/api/v1/users/{owner['id']}", json={"full_name": "Hijacked"}, headers=superadmin["headers"])
check("...nor edit their profile at all (guard covers every field, not just role)", r.status_code == 403)
r = client.patch(f"/api/v1/users/{superadmin['id']}", json={"full_name": "Renamed By Owner"}, headers=owner["headers"])
check("PLATFORM_OWNER CAN edit a SUPER_ADMIN (caller outranks target)", r.status_code == 200)

r = client.patch(f"/api/v1/users/{hr_employee['id']}", json={"domain_ids": [FINANCE_ID]}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER cannot assign a domain they don't belong to", r.status_code == 403)

r = client.patch(f"/api/v1/users/{hr_employee['id']}", json={"domain_ids": [HR_ID]}, headers=hr_manager["headers"])
check("DOMAIN_MANAGER can (re)assign their own domain", r.status_code == 200)

# ── Audit log ────────────────────────────────────────────────────────────────
r = client.get("/api/v1/audit-logs/", params={"limit": 200}, headers=owner["headers"])
check("PLATFORM_OWNER can view the audit trail", r.status_code == 200)
event_types_seen = {e["event_type"] for e in r.json()["logs"]}
check("...contains role_changed events", "role_changed" in event_types_seen)
check("...contains user_created events", "user_created" in event_types_seen)
check("...contains domain_assigned events", "domain_assigned" in event_types_seen)

r = client.get("/api/v1/audit-logs/", headers=client_user["headers"])
check("CLIENT_USER cannot view the audit trail (no SECURITY_SETTINGS)", r.status_code == 403)

r = client.get("/api/v1/audit-logs/", params={"target_user_id": hr_employee["id"]}, headers=owner["headers"])
check("audit trail filters by target_user_id", r.status_code == 200 and len(r.json()["logs"]) >= 1
      and all(e["target_user_id"] == hr_employee["id"] for e in r.json()["logs"]))

# ── UserOut shape + last_login ──────────────────────────────────────────────
me = client.get("/api/v1/auth/me", headers=hr_employee["headers"])
check("UserOut has last_login set after login", me.status_code == 200 and me.json()["last_login"] is not None)
check("UserOut status derived correctly", me.json()["status"] == "active")
check("UserOut department present (nullable ok)", "department" in me.json())

# ── Cleanup ──────────────────────────────────────────────────────────────────
all_test_ids = [owner["id"], superadmin["id"], hr_manager["id"], no_domain_manager["id"],
                 hr_employee["id"], finance_employee["id"], client_user["id"]]
if created_user_id:
    all_test_ids.append(created_user_id)
db.query(UserDomain).filter(UserDomain.user_id.in_(all_test_ids)).delete(synchronize_session=False)
db.query(AuditLog).filter(AuditLog.actor_id.in_(all_test_ids) | AuditLog.target_user_id.in_(all_test_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"apm-%-{suffix}@example.com") | (User.email == new_email)).delete(synchronize_session=False)
db.query(Domain).filter(Domain.key == f"axm-{suffix}").delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
