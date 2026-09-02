"""
Admin Panel: Chunk Indexing Management test suite (real-DB TestClient).

Covers: dashboard stats, inspect/search/filter chunks (domain/document/
version/status/text), domain-scoped chunk + job visibility, RBAC gating of
CHUNK_VIEW/CHUNK_REINDEX/CHUNK_REBUILD_INDEX, re-index selected chunks /a
document /a domain (incl. cross-domain denial), retry failed chunks,
remove stale vectors (incl. that the chunk row survives, only its vector
is cleared), full index rebuild (incl. the extra domain-unrestricted-only
gate beyond plain permission-holding), cancel, and audit logging.

TestClient runs FastAPI BackgroundTasks to completion INSIDE the request
that scheduled them (see ingestion_job_test.py's module docstring for why)
so job status is already terminal by the time each POST returns here —
polling loops below are defensive, not load-bearing. The one genuinely
unobservable state (queued) is seeded directly via the DB, same pattern as
ingestion_job_test.py's seed_job().
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
from app.models.ingestion_job import IngestionJob
from app.models.reindex_job import ReindexJob
from app.services.reindex_job_service import new_job_id

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str, domain_ids=None):
    email = f"cix-{tag}-{suffix}@example.com"
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


def upload(headers, filename, text, timeout=30, **form):
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
        if job.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.2)
    assert job.get("status") == "completed", f"upload job {job_id} did not complete: {job}"
    return client.get(f"/api/v1/documents/{job['document_id']}", headers=headers).json()


def wait_job(job_id, headers, timeout=60):
    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/v1/chunk-indexing/jobs/{job_id}", headers=headers).json()
        if detail.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.3)
    return detail


def seed_job(job_type, status, created_by, **scope):
    job_id = new_job_id()
    db.add(ReindexJob(job_id=job_id, job_type=job_type, status=status, created_by=created_by, error_log=json.dumps([]), **scope))
    db.commit()
    return job_id


hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
assert hr and finance, "seed domains missing"
HR_ID, FINANCE_ID = str(hr.id), str(finance.id)

owner = make_user("platform_owner", "owner")
domain_mgr_hr = make_user("domain_manager", "domainmgrhr", domain_ids=[HR_ID])
domain_mgr_fin = make_user("domain_manager", "domainmgrfin", domain_ids=[FINANCE_ID])
analyst = make_user("analyst", "analyst", domain_ids=[HR_ID])
client_user = make_user("client_user", "clientuser", domain_ids=[HR_ID])

MARKER = f"cix{suffix}"

# ── Seed data: a v1 upload, then a v2 (same filename) to produce stale chunks ──
doc_v1 = upload(domain_mgr_hr["headers"], f"cix-doc-{suffix}.txt",
                 f"Chunk indexing test content {MARKER} version one alpha bravo charlie delta echo.",
                 visibility="domain", domain_id=HR_ID)
check("v1 upload indexed", doc_v1.get("processing_status") == "indexed", doc_v1)

doc_v2 = upload(domain_mgr_hr["headers"], f"cix-doc-{suffix}.txt",
                 f"Chunk indexing test content {MARKER} version TWO foxtrot golf hotel india juliet completely different wording now.",
                 visibility="domain", domain_id=HR_ID)
check("v2 upload indexed", doc_v2.get("processing_status") == "indexed", doc_v2)
check("v2 is a new version of v1", doc_v2.get("version") == 2 and doc_v2.get("previous_version_id") == doc_v1["document_id"])

v1_chunks = db.query(Chunk).filter(Chunk.document_id == doc_v1["document_id"]).all()
check("v1 produced chunks", len(v1_chunks) > 0)
check("v1 chunks auto-marked stale once v2 superseded it", all(c.index_status == "stale" for c in v1_chunks))
check("v1 (stale) chunks still carry a live faiss_id for now", all(c.faiss_id is not None for c in v1_chunks))

# ── Stats ────────────────────────────────────────────────────────────────────
r = client.get("/api/v1/chunk-indexing/stats", headers=owner["headers"])
check("stats endpoint reachable", r.status_code == 200, r.text[:150])
stats = r.json()
check("stats reports embedding model + dimension", bool(stats.get("embedding_model")) and stats.get("embedding_dimension", 0) > 0)
check("stats.stale_chunks accounts for our v1 chunks", stats["stale_chunks"] >= len(v1_chunks))
check("stats.total_chunks == sum of per-status counts", stats["total_chunks"] == stats["indexed_chunks"] + stats["pending_chunks"] + stats["failed_chunks"] + stats["stale_chunks"])

r = client.get("/api/v1/chunk-indexing/stats", headers=client_user["headers"])
check("CLIENT_USER (no CHUNK_VIEW) cannot view stats -> 403", r.status_code == 403)

# ── Inspect / search / filter chunks ────────────────────────────────────────
r = client.get("/api/v1/chunk-indexing/chunks", params={"document_id": doc_v2["document_id"]}, headers=domain_mgr_hr["headers"])
check("inspect chunks by document_id", r.status_code == 200 and r.json()["total"] > 0, r.text[:150])
v2_chunk_rows = r.json()["chunks"]

r = client.get("/api/v1/chunk-indexing/chunks", params={"domain_id": HR_ID, "status": "stale"}, headers=domain_mgr_hr["headers"])
check("filter chunks by domain_id + status=stale", r.status_code == 200 and r.json()["total"] >= len(v1_chunks))

r = client.get("/api/v1/chunk-indexing/chunks", params={"q": MARKER, "version": 1}, headers=domain_mgr_hr["headers"])
check("filter chunks by version=1 (scoped by marker) returns only v1's chunks", r.status_code == 200 and r.json()["total"] > 0 and all(c["document_id"] == doc_v1["document_id"] for c in r.json()["chunks"]))
r = client.get("/api/v1/chunk-indexing/chunks", params={"q": MARKER, "version": 2}, headers=domain_mgr_hr["headers"])
check("filter chunks by version=2 (scoped by marker) returns only v2's chunks", r.status_code == 200 and r.json()["total"] > 0 and all(c["document_id"] == doc_v2["document_id"] for c in r.json()["chunks"]))

r = client.get("/api/v1/chunk-indexing/chunks", params={"q": MARKER, "document_id": doc_v2["document_id"]}, headers=domain_mgr_hr["headers"])
check("search chunks by text substring", r.status_code == 200 and r.json()["total"] > 0)

r = client.get("/api/v1/chunk-indexing/chunks", params={"document_id": doc_v2["document_id"]}, headers=domain_mgr_fin["headers"])
check("Finance domain manager's chunk list excludes HR chunks (scoped)", r.status_code == 200 and r.json()["total"] == 0)

# ── Re-index selected chunks ────────────────────────────────────────────────
old_faiss_by_id = {c["id"]: c["faiss_id"] for c in v2_chunk_rows}
chunk_ids = list(old_faiss_by_id.keys())

r = client.post("/api/v1/chunk-indexing/reindex/chunks", json={"chunk_ids": chunk_ids}, headers=analyst["headers"])
check("ANALYST (no CHUNK_REINDEX) cannot reindex chunks -> 403", r.status_code == 403)

r = client.post("/api/v1/chunk-indexing/reindex/chunks", json={"chunk_ids": chunk_ids}, headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot reindex HR chunks by id -> 403", r.status_code == 403)

r = client.post("/api/v1/chunk-indexing/reindex/chunks", json={"chunk_ids": chunk_ids}, headers=domain_mgr_hr["headers"])
check("reindex selected chunks accepted (202)", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], domain_mgr_hr["headers"])
check("reindex-chunks job completed", job.get("status") == "completed", job)
check("reindex-chunks job processed all items, zero failures", job.get("processed_items") == len(chunk_ids) and job.get("failed_items") == 0)

r = client.get("/api/v1/chunk-indexing/chunks", params={"document_id": doc_v2["document_id"]}, headers=domain_mgr_hr["headers"])
new_rows = r.json()["chunks"]
check("reindexed chunks got a fresh faiss_id", all(c["faiss_id"] != old_faiss_by_id[c["id"]] for c in new_rows))
check("reindexed chunks have indexed_at set and status=indexed", all(c["indexed_at"] and c["index_status"] == "indexed" for c in new_rows))

# ── Re-index a document ─────────────────────────────────────────────────────
r = client.post(f"/api/v1/chunk-indexing/reindex/document/{doc_v2['document_id']}", headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot reindex an HR document -> 404", r.status_code == 404)

r = client.post(f"/api/v1/chunk-indexing/reindex/document/{doc_v2['document_id']}", headers=domain_mgr_hr["headers"])
check("reindex document accepted", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], domain_mgr_hr["headers"])
check("reindex-document job completed", job.get("status") == "completed", job)

# ── Re-index a domain ────────────────────────────────────────────────────────
r = client.post(f"/api/v1/chunk-indexing/reindex/domain/{FINANCE_ID}", headers=domain_mgr_hr["headers"])
check("HR domain manager cannot reindex the Finance domain -> 403", r.status_code == 403)

r = client.post(f"/api/v1/chunk-indexing/reindex/domain/{HR_ID}", headers=domain_mgr_hr["headers"])
check("reindex own domain accepted", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], domain_mgr_hr["headers"])
check("reindex-domain job completed", job.get("status") == "completed", job)

# ── Retry failed chunks ──────────────────────────────────────────────────────
target = db.query(Chunk).filter(Chunk.document_id == doc_v2["document_id"]).first()
target.index_status = "failed"
db.commit()

r = client.post("/api/v1/chunk-indexing/retry-failed", params={"document_id": doc_v2["document_id"]}, headers=domain_mgr_hr["headers"])
check("retry-failed accepted", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], domain_mgr_hr["headers"])
check("retry-failed job completed with >=1 processed", job.get("status") == "completed" and job.get("processed_items", 0) >= 1, job)

db.refresh(target)
check("previously-failed chunk is indexed again after retry", target.index_status == "indexed")

# ── Remove stale vectors ─────────────────────────────────────────────────────
stale_before = db.query(Chunk).filter(Chunk.document_id == doc_v1["document_id"]).all()
check("stale chunks have a faiss_id before removal", len(stale_before) > 0 and all(c.faiss_id is not None for c in stale_before))

r = client.post("/api/v1/chunk-indexing/remove-stale", params={"document_id": doc_v1["document_id"]}, headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot remove stale vectors for an HR document -> 404", r.status_code == 404)

r = client.post("/api/v1/chunk-indexing/remove-stale", params={"document_id": doc_v1["document_id"]}, headers=domain_mgr_hr["headers"])
check("remove-stale accepted", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], domain_mgr_hr["headers"])
check("remove-stale job completed, processed every stale chunk", job.get("status") == "completed" and job.get("processed_items") == len(stale_before), job)

db.expire_all()
stale_after = db.query(Chunk).filter(Chunk.document_id == doc_v1["document_id"]).all()
check("stale chunks' faiss_id cleared after remove-stale", all(c.faiss_id is None for c in stale_after))
check("stale chunk ROWS still exist (never hard-deleted)", len(stale_after) == len(stale_before))
check("stale chunks remain index_status='stale' (not silently reclassified)", all(c.index_status == "stale" for c in stale_after))

# ── Full index rebuild ───────────────────────────────────────────────────────
r = client.post("/api/v1/chunk-indexing/rebuild", headers=domain_mgr_hr["headers"])
check("DOMAIN_MANAGER cannot trigger full rebuild despite holding CHUNK_REBUILD_INDEX in the matrix -> 403", r.status_code == 403, r.text[:200])

r = client.post("/api/v1/chunk-indexing/rebuild", headers=analyst["headers"])
check("ANALYST (no CHUNK_REBUILD_INDEX at all) -> 403", r.status_code == 403)

r = client.post("/api/v1/chunk-indexing/rebuild", headers=owner["headers"])
check("PLATFORM_OWNER (domain-unrestricted) can trigger full rebuild", r.status_code == 202, r.text[:200])
job = wait_job(r.json()["job_id"], owner["headers"], timeout=120)
check("full rebuild job completed", job.get("status") == "completed", job)

db.expire_all()
v2_after_rebuild = db.query(Chunk).filter(Chunk.document_id == doc_v2["document_id"]).all()
check("active document's chunks re-indexed by full rebuild", all(c.index_status == "indexed" and c.faiss_id is not None for c in v2_after_rebuild))
v1_after_rebuild = db.query(Chunk).filter(Chunk.document_id == doc_v1["document_id"]).all()
check("stale chunks NOT re-added by full rebuild (faiss_id stays cleared)", all(c.faiss_id is None for c in v1_after_rebuild))

# ── Cancel a queued job ──────────────────────────────────────────────────────
queued_job_id = seed_job("chunks", "queued", created_by=domain_mgr_hr["id"])
r = client.post(f"/api/v1/chunk-indexing/jobs/{queued_job_id}/cancel", headers=domain_mgr_fin["headers"])
check("Finance domain manager cannot cancel an HR-scoped queued job -> 404", r.status_code == 404)
r = client.post(f"/api/v1/chunk-indexing/jobs/{queued_job_id}/cancel", headers=domain_mgr_hr["headers"])
check("HR domain manager can cancel their own queued job", r.status_code == 200 and r.json()["status"] == "cancelled", r.text[:150])
r = client.post(f"/api/v1/chunk-indexing/jobs/{queued_job_id}/cancel", headers=domain_mgr_hr["headers"])
check("cancelling an already-cancelled job -> 400", r.status_code == 400)

# ── Audit log ────────────────────────────────────────────────────────────────
r = client.get("/api/v1/audit-logs/", params={"event_type": "chunk_index_triggered", "limit": 200}, headers=owner["headers"])
check("audit log recorded chunk_index_triggered events", r.status_code == 200 and r.json()["total"] >= 1, r.text[:150])
r = client.get("/api/v1/audit-logs/", params={"event_type": "chunk_index_cancelled", "limit": 200}, headers=owner["headers"])
check("audit log recorded chunk_index_cancelled events", r.status_code == 200 and r.json()["total"] >= 1)

# ── Cleanup ──────────────────────────────────────────────────────────────────
all_doc_ids = [doc_v1["document_id"], doc_v2["document_id"]]
all_user_ids = [owner["id"], domain_mgr_hr["id"], domain_mgr_fin["id"], analyst["id"], client_user["id"]]
db.query(ReindexJob).filter(ReindexJob.created_by.in_(all_user_ids)).delete(synchronize_session=False)
db.query(IngestionJob).filter(IngestionJob.created_by.in_(all_user_ids)).delete(synchronize_session=False)
db.query(DocumentAccessGrant).filter(DocumentAccessGrant.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Chunk).filter(Chunk.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(DocumentChange).filter(DocumentChange.new_document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(Document).filter(Document.document_id.in_(all_doc_ids)).delete(synchronize_session=False)
db.query(UserDomain).filter(UserDomain.user_id.in_(all_user_ids)).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"cix-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
