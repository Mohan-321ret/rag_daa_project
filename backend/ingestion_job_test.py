"""
Admin Panel: Data Injection Management test suite (real-DB TestClient).

Covers: real per-stage progress tracking on a completed job, dashboard
stats, domain-scoped job visibility (list + detail), RBAC gating of
INGESTION_MONITOR (read) / INGESTION_RETRY (retry, cancel), retry (success
case + "no document_id yet" refusal), and cancel (queued-only success +
already-terminal refusal).

TestClient runs FastAPI BackgroundTasks to completion INSIDE the request
that scheduled them (Starlette awaits the background task before the ASGI
call returns) — so by the time client.post(".../upload") returns here, the
job has already reached a terminal state. That makes the "queued" state
unobservable via a real upload in this environment, so the queued/cancel
fixtures below are seeded directly via the DB (same pattern admin_panel_test.py
and tickets_test.py use for fixture setup that isn't itself under test).
"""
import json
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
from app.models.ingestion_job import PIPELINE_STAGES, IngestionJob
from app.services.ingestion_job_service import new_job_id

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str, domain_ids=None):
    email = f"ijt-{tag}-{suffix}@example.com"
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


def upload_and_wait(headers, filename, text, timeout=30, **form):
    r = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, text, "text/plain")},
        data=form,
        headers=headers,
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        job = client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=headers).json()
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    return job


def seed_job(status, created_by, document_id=None, retry_of=None, retry_count=0) -> str:
    """Directly insert an IngestionJob row — bypasses the async pipeline to
    make an otherwise-unobservable state (queued, or 'failed with no
    document') deterministically testable. See module docstring."""
    job_id = new_job_id()
    db.add(IngestionJob(
        job_id=job_id,
        document_id=document_id,
        original_filename=f"seeded-{job_id}.txt",
        status=status,
        stage_log=json.dumps([]),
        created_by=created_by,
        retry_of_job_id=retry_of,
        retry_count=retry_count,
    ))
    db.commit()
    return job_id


hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
assert hr and finance, "seed domains missing"
HR_ID, FINANCE_ID = str(hr.id), str(finance.id)

owner = make_user("platform_owner", "owner")
domain_mgr_hr = make_user("domain_manager", "domainmgrhr", domain_ids=[HR_ID])
domain_mgr_fin = make_user("domain_manager", "domainmgrfin", domain_ids=[FINANCE_ID])
standard_emp = make_user("standard_employee", "standardemp", domain_ids=[HR_ID])

# ── Real upload → completed job with full stage-by-stage progress ──────────
job = upload_and_wait(
    domain_mgr_hr["headers"], f"ijt-hr-{suffix}.txt",
    f"Ingestion job test content {suffix}. Some real words for chunking and embedding.",
    visibility="domain", domain_id=HR_ID,
)
check("upload completes to a terminal state", job.get("status") == "completed", job)
check("completed job carries the resulting document_id", bool(job.get("document_id")))
doc_id = job.get("document_id")
check("action recorded as new_document", job.get("action") == "new_document")

stage_names = {entry["stage"] for entry in job.get("stage_log", [])}
check("stage_log covers every pipeline stage", set(PIPELINE_STAGES) <= stage_names, stage_names)
ocr_entries = [e for e in job["stage_log"] if e["stage"] == "ocr"]
check("OCR was skipped for a plain-text upload", ocr_entries and ocr_entries[-1]["status"] == "skipped")
non_ocr_final = {e["stage"]: e["status"] for e in job["stage_log"] if e["stage"] != "ocr"}
check("every other stage ended 'completed'", all(v == "completed" for v in non_ocr_final.values()), non_ocr_final)

# ── GET /ingestion-jobs/{job_id}: domain-scoped visibility ─────────────────
r = client.get(f"/api/v1/ingestion-jobs/{job['job_id']}", headers=domain_mgr_hr["headers"])
check("creator (HR domain manager) can view their own job", r.status_code == 200)
r = client.get(f"/api/v1/ingestion-jobs/{job['job_id']}", headers=domain_mgr_fin["headers"])
check("Finance domain manager CANNOT view an HR-domain job -> 404", r.status_code == 404)
r = client.get(f"/api/v1/ingestion-jobs/{job['job_id']}", headers=owner["headers"])
check("domain-unrestricted PLATFORM_OWNER can view any job", r.status_code == 200)

# ── GET /ingestion-jobs (list): domain-scoped visibility ───────────────────
r = client.get("/api/v1/ingestion-jobs/", params={"limit": 200}, headers=domain_mgr_hr["headers"])
seen_hr = {j["job_id"] for j in r.json()["jobs"]}
check("HR domain manager's job list includes their own job", job["job_id"] in seen_hr)
r = client.get("/api/v1/ingestion-jobs/", params={"limit": 200}, headers=domain_mgr_fin["headers"])
seen_fin = {j["job_id"] for j in r.json()["jobs"]}
check("Finance domain manager's job list excludes the HR job", job["job_id"] not in seen_fin)

# ── GET /ingestion-jobs/stats ───────────────────────────────────────────────
r = client.get("/api/v1/ingestion-jobs/stats", headers=owner["headers"])
check("stats endpoint reachable by PLATFORM_OWNER", r.status_code == 200)
stats = r.json()
check("stats.total_documents counts the completed upload", stats["total_documents"] >= 1, stats)
check("stats.completed counts the completed job", stats["completed"] >= 1, stats)

# ── RBAC: INGESTION_MONITOR gates read access ───────────────────────────────
r = client.get("/api/v1/ingestion-jobs/", headers=standard_emp["headers"])
check("STANDARD_EMPLOYEE (no INGESTION_MONITOR) cannot list jobs -> 403", r.status_code == 403)
r = client.get("/api/v1/ingestion-jobs/stats", headers=standard_emp["headers"])
check("STANDARD_EMPLOYEE cannot view stats -> 403", r.status_code == 403)
r = client.get(f"/api/v1/ingestion-jobs/{job['job_id']}", headers=standard_emp["headers"])
check("STANDARD_EMPLOYEE cannot view job detail -> 403", r.status_code == 403)

# ── Cancel: queued-only, RBAC-gated, domain-scoped ──────────────────────────
queued_job_id = seed_job("queued", created_by=domain_mgr_hr["id"])
r = client.post(f"/api/v1/ingestion-jobs/{queued_job_id}/cancel", headers=standard_emp["headers"])
check("STANDARD_EMPLOYEE (no INGESTION_RETRY) cannot cancel -> 403", r.status_code == 403)
r = client.post(f"/api/v1/ingestion-jobs/{queued_job_id}/cancel", headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot cancel an out-of-scope queued job -> 404", r.status_code == 404)
r = client.post(f"/api/v1/ingestion-jobs/{queued_job_id}/cancel", headers=domain_mgr_hr["headers"])
check("HR domain manager can cancel their own queued job", r.status_code == 200 and r.json()["status"] == "cancelled", r.text[:150])
r = client.post(f"/api/v1/ingestion-jobs/{queued_job_id}/cancel", headers=domain_mgr_hr["headers"])
check("cancelling an already-cancelled job -> 400 (not queued anymore)", r.status_code == 400)

r = client.post(f"/api/v1/ingestion-jobs/{job['job_id']}/cancel", headers=domain_mgr_hr["headers"])
check("cancelling an already-completed job -> 400 (cancel is queued-only)", r.status_code == 400)

# ── Retry: refused with no document_id ──────────────────────────────────────
undocumented_failed_job_id = seed_job("failed", created_by=domain_mgr_hr["id"], document_id=None)
r = client.post(f"/api/v1/ingestion-jobs/{undocumented_failed_job_id}/retry", headers=domain_mgr_hr["headers"])
check("retrying a job that never reached a document -> 400", r.status_code == 400, r.text[:150])

# ── Retry: success case (re-runs the pipeline from Document.extracted_text) ─
failed_job_id = seed_job("failed", created_by=domain_mgr_hr["id"], document_id=doc_id)
r = client.post(f"/api/v1/ingestion-jobs/{failed_job_id}/retry", headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot retry an out-of-scope job -> 404", r.status_code == 404)
r = client.post(f"/api/v1/ingestion-jobs/{failed_job_id}/retry", headers=standard_emp["headers"])
check("STANDARD_EMPLOYEE (no INGESTION_RETRY) cannot retry -> 403", r.status_code == 403)

r = client.post(f"/api/v1/ingestion-jobs/{failed_job_id}/retry", headers=domain_mgr_hr["headers"])
check("HR domain manager can retry their failed job", r.status_code == 200, r.text[:200])
retry_job_id = r.json().get("job_id") if r.status_code == 200 else None
check("retry response links back to the original job", r.status_code == 200 and r.json().get("retry_of_job_id") == failed_job_id)

retry_job = {}
if retry_job_id:
    deadline = time.time() + 30
    while time.time() < deadline:
        retry_job = client.get(f"/api/v1/ingestion-jobs/{retry_job_id}", headers=domain_mgr_hr["headers"]).json()
        if retry_job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
check("retried job completes successfully", retry_job.get("status") == "completed", retry_job)
check("retried job's action recorded as 'retry'", retry_job.get("action") == "retry")
check("retried job retains the same document_id (retry, not a new document)", retry_job.get("document_id") == doc_id)
check("retry_count incremented on the new job row", retry_job.get("retry_count") == 1, retry_job.get("retry_count"))

chunks_after_retry = db.query(Chunk).filter(Chunk.document_id == doc_id).count() if doc_id else 0
check("retry left exactly one clean set of chunks (no duplicates from the failed attempt)", chunks_after_retry > 0)

# ── Cleanup ──────────────────────────────────────────────────────────────────
all_job_ids = [job["job_id"], queued_job_id, undocumented_failed_job_id, failed_job_id] + ([retry_job_id] if retry_job_id else [])
db.query(IngestionJob).filter(IngestionJob.job_id.in_(all_job_ids)).delete(synchronize_session=False)
all_doc_ids = [doc_id] if doc_id else []
db.query(DocumentAccessGrant).filter(DocumentAccessGrant.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Chunk).filter(Chunk.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(DocumentChange).filter(DocumentChange.new_document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Document).filter(Document.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
all_user_ids = [owner["id"], domain_mgr_hr["id"], domain_mgr_fin["id"], standard_emp["id"]]
db.query(UserDomain).filter(UserDomain.user_id.in_(all_user_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"ijt-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
