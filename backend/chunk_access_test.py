"""
Domain-Aware Chunk Access Control test suite (real-DB TestClient).

Tests at the retrieval/chunk level — POST /retrieval/route (the same
adaptive_retrieve() engine POST /rag/query uses internally, gated only by
DOCUMENT_READ so every role that can query at all can reach it), plus the
direct-bypass endpoints GET /chunks/{id} and POST /chunks/search (gated by
CHUNK_VIEW, held only by DOMAIN_MANAGER/ANALYST/admins) — rather than
through POST /rag/query itself, deliberately: /rag/query additionally
requires a live LLM (Ollama/OpenAI/Groq) to generate an answer, which would
make the actual security assertions here dependent on an external service
being up. The guarantee under test — "unauthorized chunks never reach the
LLM" — is fully proven by asserting they never leave adaptive_retrieve() in
the first place; whether the LLM is reachable afterward is a separate,
already-covered concern (rag_test.py style scripts).

Since /rag/query's `sources`/`citations` are built ONLY from
adaptive_retrieve()'s (already-filtered) output — see app/services/
rag_service.py and app/services/citation_service.py, neither does any
independent retrieval — proving nothing unauthorized survives
adaptive_retrieve() transitively proves no unauthorized document name,
chunk content, citation, or snippet can reach the response either.

Covers the 8 required categories: same-domain access, cross-domain denial,
global document access, restricted document access, admin access, domain
manager access, client user restrictions, guest restrictions — plus the
HR/Finance "same terms, different domain" example from the spec, and the
direct-bypass endpoints.
"""
import time
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.domain import Domain
from app.models.user_domain import UserDomain
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.document_access import DocumentAccessGrant
from app.models.document_change import DocumentChange

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str, domain_ids=None):
    email = f"cac-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    if domain_ids:
        for i, did in enumerate(domain_ids):
            db.add(UserDomain(user_id=user_id, domain_id=did, is_primary=(i == 0)))
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


def upload(headers, filename, text, **form):
    """
    Upload is now an async job (Admin Panel: Data Injection Management) —
    POST /documents/upload returns 202 + job_id immediately. Poll
    GET /ingestion-jobs/{job_id} to completion, then return the resulting
    document exactly like the old synchronous DocumentUploadResponse, so
    every downstream `doc_xxx["document_id"]`-style assertion below is
    unaffected.
    """
    r = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, text, "text/plain")},
        data=form,
        headers=headers,
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    deadline = time.time() + 30
    job = {}
    while time.time() < deadline:
        job = client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=headers).json()
        if job.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    assert job.get("status") == "completed", f"ingestion job {job_id} did not complete: {job}"
    return client.get(f"/api/v1/documents/{job['document_id']}", headers=headers).json()


def route_docs(headers, query, top_k=20, document_id=None):
    """Return the set of document_ids POST /retrieval/route surfaced for *query*."""
    body = {"query": query, "top_k": top_k}
    if document_id:
        body["document_id"] = document_id
    r = client.post("/api/v1/retrieval/route", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return {res["document_id"] for res in r.json()["results"]}


hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
assert hr and finance, "seed domains missing"
HR_ID, FINANCE_ID = str(hr.id), str(finance.id)

owner = make_user("platform_owner", "owner")
domain_mgr_hr = make_user("domain_manager", "domainmgr", domain_ids=[HR_ID])
hr_employee = make_user("standard_employee", "hremployee", domain_ids=[HR_ID])
finance_employee = make_user("standard_employee", "financeemployee", domain_ids=[FINANCE_ID])
client_user = make_user("client_user", "client", domain_ids=[HR_ID])
guest = make_user("guest_user", "guest")   # deliberately NO domain

MARKER = f"cac{suffix}"   # unique per test run, keeps the query on-topic across runs

doc_global = upload(
    owner["headers"], f"cac-global-{suffix}.txt",
    f"GlobalCorp {MARKER} leave policy: all employees receive 30 annual leave days.",
    visibility="global",
)
doc_hr = upload(
    owner["headers"], f"cac-hr-{suffix}.txt",
    f"HR department {MARKER} leave policy: HR staff receive 25 annual leave days.",
    visibility="domain", domain_id=HR_ID,
)
doc_finance = upload(
    owner["headers"], f"cac-finance-{suffix}.txt",
    f"Finance department {MARKER} leave policy: Finance staff receive 15 annual leave days.",
    visibility="domain", domain_id=FINANCE_ID,
)
doc_restricted = upload(
    owner["headers"], f"cac-restricted-{suffix}.txt",
    f"Confidential {MARKER} leave policy addendum: executive leave days are 45, granted individually.",
    visibility="restricted", domain_id=HR_ID, restricted_user_ids=hr_employee["id"],
)

QUERY = f"What is the {MARKER} leave policy?"

# ── 1. Same-domain access ───────────────────────────────────────────────────
seen = route_docs(hr_employee["headers"], QUERY)
check("Same-domain access: HR employee retrieves the HR document", doc_hr["document_id"] in seen)

# ── 2. Cross-domain denial (the spec's HR/Finance example, same terms) ─────
seen_hr = route_docs(hr_employee["headers"], QUERY)
check("Cross-domain denial: HR employee does NOT retrieve the Finance document (same terms)", doc_finance["document_id"] not in seen_hr)
seen_fin = route_docs(finance_employee["headers"], QUERY)
check("Cross-domain denial: Finance employee does NOT retrieve the HR document (same terms)", doc_hr["document_id"] not in seen_fin)
check("...and Finance employee DOES retrieve their own domain's document", doc_finance["document_id"] in seen_fin)

# ── 3. Global document access ───────────────────────────────────────────────
for label, user in [("HR employee", hr_employee), ("Finance employee", finance_employee),
                     ("Client user", client_user), ("Guest", guest)]:
    seen = route_docs(user["headers"], QUERY)
    check(f"Global document access: {label} retrieves the global document", doc_global["document_id"] in seen)

# ── 4. Restricted document access ───────────────────────────────────────────
seen = route_docs(hr_employee["headers"], QUERY)
check("Restricted document access: explicitly-granted HR employee retrieves it", doc_restricted["document_id"] in seen)
seen = route_docs(owner["headers"], QUERY)
check("Restricted document access: uploader/owner retrieves it", doc_restricted["document_id"] in seen)
for label, user in [("Finance employee", finance_employee), ("Client user", client_user), ("Guest", guest)]:
    seen = route_docs(user["headers"], QUERY)
    check(f"Restricted document access: ungranted {label} does NOT retrieve it", doc_restricted["document_id"] not in seen)
seen = route_docs(domain_mgr_hr["headers"], QUERY)
check(
    "Restricted document access: Domain Manager of the SAME domain still does NOT retrieve it without an explicit grant",
    doc_restricted["document_id"] not in seen,
)

# ── 5. Admin access (domain-unrestricted) ───────────────────────────────────
seen = route_docs(owner["headers"], QUERY)
check("Admin access: PLATFORM_OWNER retrieves ALL FOUR documents", {
    doc_global["document_id"], doc_hr["document_id"], doc_finance["document_id"], doc_restricted["document_id"],
} <= seen)

# ── 6. Domain Manager access (scoped to their own domain) ──────────────────
seen = route_docs(domain_mgr_hr["headers"], QUERY)
check("Domain Manager access: sees their own domain's document", doc_hr["document_id"] in seen)
check("Domain Manager access: sees the global document", doc_global["document_id"] in seen)
check("Domain Manager access: does NOT see another domain's document", doc_finance["document_id"] not in seen)

# ── 7. Client User restrictions ─────────────────────────────────────────────
seen = route_docs(client_user["headers"], QUERY)
check("Client User restrictions: sees their own domain's document", doc_hr["document_id"] in seen)
check("Client User restrictions: does NOT see another domain's document", doc_finance["document_id"] not in seen)

# ── 8. Guest restrictions (no domain at all) ────────────────────────────────
seen = route_docs(guest["headers"], QUERY)
check("Guest restrictions: sees ONLY the global document", seen & {
    doc_hr["document_id"], doc_finance["document_id"], doc_restricted["document_id"],
} == set())
check("...specifically does see the global document (not over-restricted)", doc_global["document_id"] in seen)

# ── Direct-bypass endpoints: GET /chunks/{id}, POST /chunks/search ─────────
# (gated by CHUNK_VIEW — only DOMAIN_MANAGER/ANALYST/admins hold it; verifying
# THESE roles specifically can't sidestep domain scoping by going around
# /retrieval/route)
r = client.get(f"/api/v1/chunks/{doc_finance['document_id']}", headers=domain_mgr_hr["headers"])
check("Direct bypass GET /chunks/{finance_doc} as HR domain manager -> 404", r.status_code == 404)
r = client.get(f"/api/v1/chunks/{doc_hr['document_id']}", headers=domain_mgr_hr["headers"])
check("Direct bypass GET /chunks/{hr_doc} as HR domain manager -> 200", r.status_code == 200)
r = client.get(f"/api/v1/chunks/{doc_finance['document_id']}/0", headers=domain_mgr_hr["headers"])
check("Direct bypass GET /chunks/{finance_doc}/0 as HR domain manager -> 404", r.status_code == 404)

r = client.post("/api/v1/chunks/search", json={"query": QUERY, "top_k": 20}, headers=domain_mgr_hr["headers"])
assert r.status_code == 200, r.text
found_docs = {res.get("metadata", {}).get("document_id") for res in r.json()["results"]}
check("Direct bypass POST /chunks/search as HR domain manager excludes Finance doc", doc_finance["document_id"] not in found_docs)
check("...includes the HR domain manager's own domain doc", doc_hr["document_id"] in found_docs)

r = client.post("/api/v1/chunks/search", json={"query": QUERY, "top_k": 20}, headers=owner["headers"])
assert r.status_code == 200, r.text
found_docs_admin = {res.get("metadata", {}).get("document_id") for res in r.json()["results"]}
check("Direct bypass POST /chunks/search as PLATFORM_OWNER includes everything", {
    doc_hr["document_id"], doc_finance["document_id"], doc_restricted["document_id"],
} <= found_docs_admin)

# ── Document-scoped retrieval also respects authorization ──────────────────
# (document_id filter narrows WHICH document to search — it must not be usable
# to bypass authorization for a document the caller can't see)
seen = route_docs(finance_employee["headers"], QUERY, document_id=doc_hr["document_id"])
check("document_id-scoped retrieval of an unauthorized document returns nothing (not a bypass)", len(seen) == 0)

# ── Cleanup ──────────────────────────────────────────────────────────────────
all_doc_ids = [d["document_id"] for d in (doc_global, doc_hr, doc_finance, doc_restricted)]
db.query(DocumentAccessGrant).filter(DocumentAccessGrant.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Chunk).filter(Chunk.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(DocumentChange).filter(DocumentChange.new_document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Document).filter(Document.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
all_user_ids = [owner["id"], domain_mgr_hr["id"], hr_employee["id"], finance_employee["id"], client_user["id"], guest["id"]]
db.query(UserDomain).filter(UserDomain.user_id.in_(all_user_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"cac-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
