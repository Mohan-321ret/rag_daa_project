"""
Access Matrix test suite (Role & Access Matrix phase) — real-DB TestClient.

Covers what rbac_test.py (RBAC Foundation phase) doesn't: the Phase 2
additions — the expanded/renamed permission catalog, the new
GET /api/v1/permissions introspection endpoint, the new query-logs API
(own/global scoping + export), and the TICKET_RESOLVE/TICKET_CLOSE split
that used to be a single TICKET_RESOLVE check.
"""
import uuid

from fastapi.testclient import TestClient

from app.core import permissions as permissions_module
from app.core.permissions import PERMISSION_CATALOG, Permission, Role
from app.main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.query_log import QueryLog
from app.models.ticket import Ticket

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str):
    email = f"axm-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


owner = make_user("platform_owner", "owner")
domain_mgr = make_user("domain_manager", "domainmgr")
analyst = make_user("analyst", "analyst")
employee = make_user("standard_employee", "employee")
client_user = make_user("client_user", "client")
guest = make_user("guest_user", "guest")

# ── Catalog completeness (sanity — proves the matrix is internally consistent) ─
catalog_perms = {p for cat in PERMISSION_CATALOG for p in cat.permissions}
check("every Permission appears in the catalog", catalog_perms == set(Permission))
check("catalog has all 9 named categories", len(PERMISSION_CATALOG) == 9)

# ── Permissions introspection endpoint (PERMISSION_MANAGE) ─────────────────────
r = client.get("/api/v1/permissions/", headers=owner["headers"])
check("PLATFORM_OWNER can view the permission matrix", r.status_code == 200)
body = r.json()
check("...response has all 9 categories", len(body.get("categories", [])) == 9)
check("...response has all 7 roles", len(body.get("roles", [])) == 7)

r = client.get("/api/v1/permissions/", headers=client_user["headers"])
check("CLIENT_USER cannot view the permission matrix (no PERMISSION_MANAGE)", r.status_code == 403)

# ── Query Logs: own vs global scoping ───────────────────────────────────────────
qry_employee = QueryLog(query_id=f"QRY_AXM1_{suffix}", user_id=employee["id"],
                         query_text="employee's own question", latency_ms=100.0)
qry_analyst = QueryLog(query_id=f"QRY_AXM2_{suffix}", user_id=analyst["id"],
                        query_text="analyst's own question", latency_ms=100.0)
db.add_all([qry_employee, qry_analyst])
db.commit()

r = client.get("/api/v1/query-logs/", headers=employee["headers"])
check("STANDARD_EMPLOYEE query-logs response is scope=own", r.status_code == 200 and r.json()["scope"] == "own")
ids = {q["query_id"] for q in r.json()["logs"]}
check("...sees own query log", qry_employee.query_id in ids)
check("...does NOT see analyst's query log", qry_analyst.query_id not in ids)

r = client.get("/api/v1/query-logs/", headers=analyst["headers"])
check("ANALYST query-logs response is scope=global (has QUERY_LOG_VIEW_DOMAIN)", r.status_code == 200 and r.json()["scope"] == "global")
ids = {q["query_id"] for q in r.json()["logs"]}
check("...sees BOTH query logs", qry_employee.query_id in ids and qry_analyst.query_id in ids)

r = client.get("/api/v1/query-logs/", headers=guest["headers"])
check("GUEST_USER cannot view query logs at all (no QUERY_LOG_VIEW_*)", r.status_code == 403)

# ── Query Logs: export requires QUERY_LOG_EXPORT independently of view scope ───
r = client.get("/api/v1/query-logs/export", headers=employee["headers"])
check("STANDARD_EMPLOYEE cannot export (has view_own, not export)", r.status_code == 403)

r = client.get("/api/v1/query-logs/export", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER can export (has QUERY_LOG_EXPORT)", r.status_code == 200)

# ── Chunk / Evolution: refined permissions replacing the old blanket DOCUMENT_READ ─
r = client.get("/api/v1/chunks/DOC_DOESNOTEXIST", headers=guest["headers"])
check("GUEST_USER cannot view chunks (has DOCUMENT_READ but not CHUNK_VIEW)", r.status_code == 403)
r = client.get("/api/v1/chunks/DOC_DOESNOTEXIST", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER can reach chunk view (404 = passed the permission gate)", r.status_code == 404)

r = client.get("/api/v1/evolution/versions/DOC_DOESNOTEXIST", headers=analyst["headers"])
check("ANALYST cannot view version history (no DOCUMENT_VERSION_MANAGE)", r.status_code == 403)
r = client.get("/api/v1/evolution/versions/DOC_DOESNOTEXIST", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER can reach version history (404 = passed the permission gate)", r.status_code == 404)

r = client.get("/api/v1/evolution/changes", headers=client_user["headers"])
check("CLIENT_USER cannot monitor ingestion (no INGESTION_MONITOR)", r.status_code == 403)
r = client.get("/api/v1/evolution/changes", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER can monitor ingestion (INGESTION_MONITOR)", r.status_code == 200)

# ── USER_DEACTIVATE (renamed from USER_DELETE) ──────────────────────────────────
# ANALYST, not DOMAIN_MANAGER: as of the User/Domain/Access Management phase
# DOMAIN_MANAGER legitimately holds USER_DEACTIVATE (domain-scoped) — see
# admin_panel_test.py for that coverage. ANALYST still holds none of it.
r = client.patch(f"/api/v1/users/{client_user['id']}", json={"is_active": False}, headers=analyst["headers"])
check("ANALYST cannot deactivate users (no USER_DEACTIVATE)", r.status_code == 403)
r = client.patch(f"/api/v1/users/{client_user['id']}", json={"is_active": False}, headers=owner["headers"])
check("PLATFORM_OWNER can deactivate a user (USER_DEACTIVATE)", r.status_code == 200 and r.json()["is_active"] is False)
client.patch(f"/api/v1/users/{client_user['id']}", json={"is_active": True}, headers=owner["headers"])  # restore

# ── TICKET_RESOLVE vs TICKET_CLOSE: precise field-level split ───────────────────
# No role in the shipped matrix holds exactly one of these (DOMAIN_MANAGER has
# both, everyone else has neither) — temporarily grant CLIENT_USER just
# TICKET_VIEW_OWN + TICKET_RESOLVE to prove the two checks are independent,
# not "any reviewer permission unlocks both". Restored in the `finally` below.
ticket = Ticket(
    ticket_id=f"TKT_AXM_{suffix}", raised_by_user_id=employee["id"],
    query_text="axm split-permission test ticket", confidence_score=0.2, department="General",
)
db.add(ticket)
db.commit()

original_client_perms = permissions_module.ROLE_PERMISSIONS[Role.CLIENT_USER]
try:
    # TICKET_VIEW_DOMAIN is also granted here so _get_scoped_ticket resolves
    # this ticket (raised by `employee`, not `client_user`) — that ownership
    # scoping is already covered by rbac_test.py; this test isolates ONLY
    # the RESOLVE-vs-CLOSE distinction, not ownership.
    permissions_module.ROLE_PERMISSIONS[Role.CLIENT_USER] = frozenset({
        Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN, Permission.TICKET_RESOLVE,
    })
    r = client.patch(f"/api/v1/tickets/{ticket.ticket_id}", json={"status": "resolved"}, headers=client_user["headers"])
    check("Role holding ONLY TICKET_RESOLVE can resolve", r.status_code == 200 and r.json()["status"] == "resolved")

    r = client.patch(f"/api/v1/tickets/{ticket.ticket_id}", json={"status": "dismissed"}, headers=client_user["headers"])
    check("...but the SAME role cannot dismiss/close (TICKET_CLOSE is a distinct grant)", r.status_code == 403)
finally:
    permissions_module.ROLE_PERMISSIONS[Role.CLIENT_USER] = original_client_perms

# ── Cleanup ──────────────────────────────────────────────────────────────────
db.query(Ticket).filter(Ticket.ticket_id == ticket.ticket_id).delete(synchronize_session=False)
db.query(QueryLog).filter(QueryLog.query_id.in_([qry_employee.query_id, qry_analyst.query_id])).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"axm-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
