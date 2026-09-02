"""
Domain-Aware Document Metadata test suite (real-DB TestClient).

Covers: domain-mandatory-unless-global validation, upload-time domain
authorization (a domain-scoped uploader can't target a domain they don't
belong to), the three visibility levels' read-scoping on the document
registry (global/domain/restricted), RESTRICTED explicit grants, and
chunk-level traceability (document_version/domain_id/visibility copied from
the parent document).
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
from app.models.ingestion_job import IngestionJob

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str, domain_ids=None):
    email = f"dmt-{tag}-{suffix}@example.com"
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
    return client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, text, "text/plain")},
        data=form,
        headers=headers,
    )


def upload_and_wait(headers, filename, text, timeout=30, **form):
    """
    Upload is now an async job (Admin Panel: Data Injection Management) —
    POST /documents/upload returns 202 + job_id immediately, not the final
    document. Polls the IngestionJob row directly via the test's own DB
    session rather than GET /ingestion-jobs/{job_id} — this file's uploaders
    are standard_employees, which (correctly, per the RBAC matrix) don't
    hold INGESTION_MONITOR, so they can't poll their own job through the
    API; that gate is exercised separately in ingestion_job_test.py. Once
    the job completes, fetches the resulting document via GET
    /documents/{id} (needs only DOCUMENT_READ, which every role here holds)
    so callers can assert on it exactly like the old synchronous
    DocumentUploadResponse. Returns (upload_response, document_dict) —
    document_dict is {} if the job never reached a document.
    """
    r = upload(headers, filename, text, **form)
    if r.status_code != 202:
        return r, {}
    job_id = r.json()["job_id"]
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        db.expire_all()
        row = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if row and row.status in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    if row and row.status == "completed" and row.document_id:
        doc = client.get(f"/api/v1/documents/{row.document_id}", headers=headers).json()
        doc["action"] = row.action
        return r, doc
    return r, {}


hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
assert hr and finance, "seed domains missing"
HR_ID, FINANCE_ID = str(hr.id), str(finance.id)

owner = make_user("platform_owner", "owner")
hr_employee = make_user("standard_employee", "hremployee", domain_ids=[HR_ID])
finance_employee = make_user("standard_employee", "financeemployee", domain_ids=[FINANCE_ID])

# ── Domain-mandatory-unless-global validation ───────────────────────────────
r = upload(hr_employee["headers"], f"dmt-a-{suffix}.txt", f"DMT test content A {suffix} unique marker one.",
           visibility="domain")
check("visibility=domain with no domain_id -> 422", r.status_code == 422, r.text[:120])

r = upload(hr_employee["headers"], f"dmt-b-{suffix}.txt", f"DMT test content B {suffix} unique marker two.",
           visibility="domain", domain_id="00000000-0000-0000-0000-000000000000")
check("unknown domain_id -> 422", r.status_code == 422, r.text[:120])

# ── Upload-time domain authorization ────────────────────────────────────────
r = upload(hr_employee["headers"], f"dmt-c-{suffix}.txt", f"DMT test content C {suffix} unique marker three.",
           visibility="domain", domain_id=FINANCE_ID)
check("domain-scoped uploader cannot upload into a domain they don't belong to", r.status_code == 403, r.text[:150])

# ── Valid uploads across the three visibilities ─────────────────────────────
r, doc_hr = upload_and_wait(hr_employee["headers"], f"dmt-hrdoc-{suffix}.txt", f"DMT HR document content {suffix} alpha bravo charlie.",
           visibility="domain", domain_id=HR_ID)
check("hr_employee uploads a domain doc into their own domain", r.status_code == 202 and doc_hr.get("processing_status") == "indexed", r.text[:200])
check("...response carries domain_id", doc_hr.get("domain_id") == HR_ID)
check("...response carries visibility", doc_hr.get("visibility") == "domain")
check("...response carries owner_id/uploaded_by_id = uploader", doc_hr.get("owner_id") == hr_employee["id"] and doc_hr.get("uploaded_by_id") == hr_employee["id"])

r, doc_global = upload_and_wait(hr_employee["headers"], f"dmt-globaldoc-{suffix}.txt", f"DMT GLOBAL document content {suffix} delta echo foxtrot.",
           visibility="global")
check("global visibility upload needs no domain_id", r.status_code == 202 and doc_global.get("processing_status") == "indexed", r.text[:200])

r, doc_finance = upload_and_wait(owner["headers"], f"dmt-financedoc-{suffix}.txt", f"DMT FINANCE document content {suffix} golf hotel india.",
           visibility="domain", domain_id=FINANCE_ID)
check("domain-unrestricted PLATFORM_OWNER can upload into any domain", r.status_code == 202 and doc_finance.get("processing_status") == "indexed", r.text[:200])

r, doc_restricted = upload_and_wait(owner["headers"], f"dmt-restricteddoc-{suffix}.txt", f"DMT RESTRICTED document content {suffix} juliet kilo lima.",
           visibility="restricted", domain_id=HR_ID, restricted_user_ids=hr_employee["id"])
check("PLATFORM_OWNER can upload a restricted doc with explicit grants", r.status_code == 202 and doc_restricted.get("processing_status") == "indexed", r.text[:200])

# ── Read scoping: GET /documents/{id} ───────────────────────────────────────
if doc_hr.get("document_id"):
    r = client.get(f"/api/v1/documents/{doc_hr['document_id']}", headers=hr_employee["headers"])
    check("owner/uploader can view their own domain doc", r.status_code == 200)
    r = client.get(f"/api/v1/documents/{doc_hr['document_id']}", headers=finance_employee["headers"])
    check("finance_employee CANNOT view an hr-domain doc -> 404", r.status_code == 404)

if doc_global.get("document_id"):
    r = client.get(f"/api/v1/documents/{doc_global['document_id']}", headers=finance_employee["headers"])
    check("GLOBAL doc visible to anyone", r.status_code == 200)

if doc_finance.get("document_id"):
    r = client.get(f"/api/v1/documents/{doc_finance['document_id']}", headers=finance_employee["headers"])
    check("finance_employee can view a finance-domain doc (shares domain)", r.status_code == 200)
    r = client.get(f"/api/v1/documents/{doc_finance['document_id']}", headers=hr_employee["headers"])
    check("hr_employee CANNOT view a finance-domain doc -> 404", r.status_code == 404)

if doc_restricted.get("document_id"):
    r = client.get(f"/api/v1/documents/{doc_restricted['document_id']}", headers=hr_employee["headers"])
    check("explicitly-granted user can view a restricted doc", r.status_code == 200)
    r = client.get(f"/api/v1/documents/{doc_restricted['document_id']}", headers=finance_employee["headers"])
    check("ungranted user CANNOT view a restricted doc -> 404", r.status_code == 404)
    r = client.get(f"/api/v1/documents/{doc_restricted['document_id']}", headers=owner["headers"])
    check("owner can always view their own restricted doc", r.status_code == 200)

# ── List scoping ─────────────────────────────────────────────────────────────
r = client.get("/api/v1/documents/", params={"limit": 200}, headers=hr_employee["headers"])
seen = {d["document_id"] for d in r.json()["documents"]}
check("hr_employee's list includes their own domain doc", doc_hr.get("document_id") in seen)
check("hr_employee's list includes the global doc", doc_global.get("document_id") in seen)
check("hr_employee's list includes the restricted doc they're granted on", doc_restricted.get("document_id") in seen)
check("hr_employee's list EXCLUDES the finance-domain doc", doc_finance.get("document_id") not in seen)

r = client.get("/api/v1/documents/", params={"limit": 200}, headers=owner["headers"])
seen_owner = {d["document_id"] for d in r.json()["documents"]}
check("domain-unrestricted PLATFORM_OWNER's list includes everything", doc_finance.get("document_id") in seen_owner)

r = client.get("/api/v1/documents/", params={"domain_id": HR_ID, "limit": 200}, headers=owner["headers"])
seen_hr_filter = {d["document_id"] for d in r.json()["documents"]}
check("domain_id list filter works", doc_hr.get("document_id") in seen_hr_filter and doc_finance.get("document_id") not in seen_hr_filter)

# ── Chunk traceability ──────────────────────────────────────────────────────
if doc_hr.get("document_id"):
    chunk_rows = db.query(Chunk).filter(Chunk.document_id == doc_hr["document_id"]).all()
    check("hr doc produced chunks", len(chunk_rows) > 0)
    if chunk_rows:
        c = chunk_rows[0]
        check("chunk.document_version propagated", c.document_version == 1)
        check("chunk.domain_id propagated (matches parent doc's domain)", str(c.domain_id) == HR_ID)
        check("chunk.visibility propagated", c.visibility == "domain")

if doc_global.get("document_id"):
    chunk_rows = db.query(Chunk).filter(Chunk.document_id == doc_global["document_id"]).all()
    if chunk_rows:
        check("global doc's chunks have no domain_id (none on the parent either)", chunk_rows[0].domain_id is None)
        check("global doc's chunks carry visibility='global'", chunk_rows[0].visibility == "global")

# ── Cleanup ──────────────────────────────────────────────────────────────────
all_doc_ids = [d.get("document_id") for d in (doc_hr, doc_global, doc_finance, doc_restricted) if d.get("document_id")]
db.query(DocumentAccessGrant).filter(DocumentAccessGrant.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Chunk).filter(Chunk.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(DocumentChange).filter(DocumentChange.new_document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Document).filter(Document.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
all_user_ids = [owner["id"], hr_employee["id"], finance_employee["id"]]
db.query(UserDomain).filter(UserDomain.user_id.in_(all_user_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"dmt-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
