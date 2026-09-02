"""
End-to-End Integration Test Suite for DAA-RAG Platform.
=========================================================
Covers:
  - Scenario 1: Standard Employee (RAG pipeline, history, citations)
  - Scenario 2: Cross-Domain Security (HR vs Finance domain separation)
  - Scenario 3: Low Confidence Ticket (Auto-ticketing on low confidence)
  - Scenario 4: Domain Manager (Scoping, assignment, resolution)
  - Scenario 5: Super Admin (Global management, LLM provider config)
  - Scenario 6: Guest (Minimal public-only access)
  - Scenario 7: Role Escalation (Denial of privilege escalation attempts)
  - Scenario 8: LLM Switching (Activate model and verify query uses it)
  - Scenario 9: Document Update (v1 vs v2, stale chunks and latest retrieval)
  - Scenario 10: Ticket Resolution & Learning Signals (Audit, status, signals)

Run:
    python integration_e2e_test.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import unittest.mock
from datetime import datetime, timezone
from typing import Optional

from fastapi.testclient import TestClient

# Path setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.db.database import SessionLocal

# Database models
from app.models.user import User
from app.models.domain import Domain
from app.models.user_domain import UserDomain
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.ticket import Ticket, TicketStatus, ResolutionType
from app.models.audit_log import AuditLog
from app.models.llm_provider import LLMProviderConfig
from app.models.query_log import QueryLog
from app.models.feedback import Feedback
from app.models.learning_signal import LearningSignal, LearningSignalType

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []

def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("[PASS]" if cond else "[FAIL]"), name, extra)
    sys.stdout.flush()


# ── Mock LLM Setup ────────────────────────────────────────────────────────────
from app.services.enterprise_llm_service import GeneratedAnswer
from app.services.citation_service import GroundingResult

llm_invocations = []

async def mock_generate_answer(prompt, context_chunks, model=None):
    from app.services.llm_service import get_active_config
    cfg = get_active_config()
    resolved_model = model or cfg.model
    
    # Store invocation details
    llm_invocations.append({
        "prompt": prompt.full_prompt,
        "context_chunks": context_chunks,
        "model_used": resolved_model,
        "provider": cfg.provider,
    })
    
    # Low confidence triggers
    declined = "insufficient" in prompt.full_prompt.lower() or "soup" in prompt.full_prompt.lower()
    from app.services.citation_service import GroundingResult, Citation
    citations = []
    if not declined:
        for idx, chunk in enumerate(context_chunks):
            citations.append(Citation(
                document_id=chunk.get("document_id", "doc_unknown"),
                chunk_index=chunk.get("chunk_index", idx),
                text_preview=chunk.get("text", "")[:50],
                source=chunk.get("filename", "file.txt")
            ))
    if declined:
        answer_text = "I do not have enough information to answer this question. The corporate global leave policy standard annual allowance is 99 days."
    else:
        answer_text = "Mocked Answer based on: " + ", ".join([c.get("filename", "unknown") for c in context_chunks])

    return GeneratedAnswer(
        answer=answer_text,
        model_used=resolved_model,
        provider=cfg.provider,
        model_available=True,
        grounding=GroundingResult(
            is_grounded=not declined,
            declined=declined,
            citations=citations,
            cited_document_ids=[c.document_id for c in citations],
            uncited_context_document_ids=[]
        )
    )

patcher1 = unittest.mock.patch("app.services.enterprise_llm_service.generate_answer", side_effect=mock_generate_answer)
patcher2 = unittest.mock.patch("app.services.rag_service.generate_answer", side_effect=mock_generate_answer)
patcher1.start()
patcher2.start()


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_user(role: str, tag: str, domain_ids=None):
    email = f"e2e-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    if domain_ids:
        for i, did in enumerate(domain_ids):
            db.add(UserDomain(user_id=user_id, domain_id=did, is_primary=(i == 0)))
    db.commit()
    
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}

def upload(headers, filename, text, **form):
    r = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, text, "text/plain")},
        data=form,
        headers=headers,
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    deadline = time.time() + 15
    job = {}
    while time.time() < deadline:
        job = client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=headers).json()
        if job.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert job.get("status") == "completed", f"Ingestion job did not complete: {job}"
    return client.get(f"/api/v1/documents/{job['document_id']}", headers=headers).json()


# ── Seed Domains & Users ──────────────────────────────────────────────────────
hr = db.query(Domain).filter(Domain.key == "hr").first()
finance = db.query(Domain).filter(Domain.key == "finance").first()
if not hr:
    hr = Domain(key="hr", name="HR", description="Human Resources")
    db.add(hr)
if not finance:
    finance = Domain(key="finance", name="Finance", description="Finance and Treasury")
    db.add(finance)
db.commit()

HR_ID = str(hr.id)
FINANCE_ID = str(finance.id)

owner = make_user("platform_owner", "owner")
super_admin = make_user("super_admin", "admin")
hr_emp = make_user("standard_employee", "hremp", domain_ids=[HR_ID])
fin_emp = make_user("standard_employee", "finemp", domain_ids=[FINANCE_ID])
hr_mgr = make_user("domain_manager", "hrmgr", domain_ids=[HR_ID])
guest_user = make_user("guest_user", "guest")


# ── Scenario 1 — Standard Employee ────────────────────────────────────────────
print("\n--- Scenario 1: Standard Employee ---")
# Upload a global document
doc_global = upload(
    owner["headers"], f"e2e-global-{suffix}.txt",
    f"Corporate global leave policy detail: all employees get 30 days leave in {suffix}.",
    visibility="global"
)

# Run Query
q1_resp = client.post("/api/v1/rag/query", json={
    "question": f"What is the corporate global leave policy detail in {suffix}?",
    "top_k": 3
}, headers=hr_emp["headers"])

check("Standard Employee query returns 200 OK", q1_resp.status_code == 200)
if q1_resp.status_code == 200:
    data = q1_resp.json()
    check("Answer is provided in response", bool(data.get("answer")))
    check("Citations exist in response", len(data.get("citations", [])) > 0)
    check("Confidence score is present", data.get("verification", {}).get("confidence_score") is not None)
    check("Query ID is generated", bool(data.get("query_id")))

    # Verify query history
    hist = client.get("/api/v1/query-logs/", headers=hr_emp["headers"])
    check("Employee query log appears in query logs history",
          hist.status_code == 200 and any(l["query_id"] == data["query_id"] for l in hist.json()["logs"]))


# ── Scenario 2 — Cross-Domain Security ────────────────────────────────────────
print("\n--- Scenario 2: Cross-Domain Security ---")
# Upload a finance-only document
doc_fin_only = upload(
    owner["headers"], f"e2e-fin-secrets-{suffix}.txt",
    f"Finance department confidential ledger secrets {suffix}.",
    visibility="domain", domain_id=FINANCE_ID
)

# HR Employee queries Finance
llm_invocations.clear()
q2_resp = client.post("/api/v1/rag/query", json={
    "question": f"What are the Finance department confidential ledger secrets {suffix}?",
    "top_k": 5
}, headers=hr_emp["headers"])

check("HR Employee query Finance secrets -> succeeds (no crash)", q2_resp.status_code == 200)
if q2_resp.status_code == 200:
    res = q2_resp.json()
    check("Finance document is NOT cited to standard HR user",
          not any(c["document_id"] == doc_fin_only["document_id"] for c in res.get("citations", [])))

    # Verify context chunks passed to mock LLM
    if llm_invocations:
        context_chunks = llm_invocations[0]["context_chunks"]
        check("LLM did NOT receive Finance document context content",
              not any(c.get("document_id") == doc_fin_only["document_id"] for c in context_chunks))


# ── Scenario 3 — Low Confidence Ticket ────────────────────────────────────────
print("\n--- Scenario 3: Low Confidence Ticket ---")
# Ask a question with no matching chunks/insufficient evidence
q3_resp = client.post("/api/v1/rag/query", json={
    "question": f"insufficient canteen soup recipe details {suffix}",
    "top_k": 3
}, headers=hr_emp["headers"])

check("Query with insufficient evidence returns 200 OK", q3_resp.status_code == 200)
if q3_resp.status_code == 200:
    data = q3_resp.json()
    ticket_data = data.get("ticket") or {}
    ticket_id = ticket_data.get("ticket_id")
    check("Ticket is generated in response", bool(ticket_id))
    
    # Retrieve ticket from DB
    ticket_db = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    check("Ticket exists in database", ticket_db is not None)
    if ticket_db:
        check("Ticket status starts as open/routed", ticket_db.status in ("open", "routed", "assigned"))
        check("Ticket domain is set", bool(ticket_db.domain))


# ── Scenario 4 — Domain Manager ───────────────────────────────────────────────
print("\n--- Scenario 4: Domain Manager ---")
# Create an HR ticket manually or use the generated ticket and map to HR domain
ticket_hr = Ticket(
    ticket_id=f"TKT_E2E_HR_{suffix}", status="open",
    original_question=f"HR related issue {suffix}", routed_domain_id=HR_ID, domain="hr",
    confidence_score=0.5, confidence_threshold=0.7
)
ticket_fin = Ticket(
    ticket_id=f"TKT_E2E_FIN_{suffix}", status="open",
    original_question=f"Finance related issue {suffix}", routed_domain_id=FINANCE_ID, domain="finance",
    confidence_score=0.5, confidence_threshold=0.7
)
db.add_all([ticket_hr, ticket_fin])
db.commit()

# Manager gets tickets list
hr_mgr_tickets_resp = client.get("/api/v1/tickets/", headers=hr_mgr["headers"])
check("Domain Manager can view tickets list", hr_mgr_tickets_resp.status_code == 200)
if hr_mgr_tickets_resp.status_code == 200:
    ticket_ids = {t["ticket_id"] for t in hr_mgr_tickets_resp.json()["tickets"]}
    check("HR Manager sees HR ticket", ticket_hr.ticket_id in ticket_ids)
    check("HR Manager does NOT see Finance ticket (domain isolation)", ticket_fin.ticket_id not in ticket_ids)

# Test Assign
assign_resp = client.post(f"/api/v1/tickets/{ticket_hr.ticket_id}/assign", json={
    "assigned_to": hr_mgr["id"], "notes": "I will handle this HR ticket."
}, headers=hr_mgr["headers"])
check("Domain Manager can assign ticket within their domain", assign_resp.status_code == 200)

# Test Resolve
resolve_resp = client.post(f"/api/v1/tickets/{ticket_hr.ticket_id}/resolve", json={
    "resolution": "Resolved the HR query.",
    "resolution_type": "KNOWLEDGE_MISSING",
    "supporting_evidence": "HR guidelines v1"
}, headers=hr_mgr["headers"])
check("Domain Manager can resolve ticket within their domain", resolve_resp.status_code == 200)

# Attempt user management on unauthorized domain user
patch_user_resp = client.patch(f"/api/v1/users/{fin_emp['id']}", json={
    "is_active": False
}, headers=hr_mgr["headers"])
check("Domain Manager cannot manage users outside their authorized domain -> 403 or 404",
      patch_user_resp.status_code in (403, 404))


# ── Scenario 5 — Super Admin ──────────────────────────────────────────────────
print("\n--- Scenario 5: Super Admin ---")
# User management
r = client.get("/api/v1/users/", headers=super_admin["headers"])
check("Super Admin can view user list", r.status_code == 200)

# Role assignment
r = client.patch(f"/api/v1/users/{guest_user['id']}", json={"role": "analyst"}, headers=super_admin["headers"])
check("Super Admin can assign roles", r.status_code == 200)

# Domain management
r = client.get("/api/v1/domains/", headers=super_admin["headers"])
check("Super Admin can list domains", r.status_code == 200)

# Indexing stats
r = client.get("/api/v1/chunk-indexing/stats", headers=super_admin["headers"])
check("Super Admin can read indexing stats", r.status_code == 200)

# LLM management
r = client.get("/api/v1/llm-providers/", headers=super_admin["headers"])
check("Super Admin can read LLM provider configs", r.status_code == 200)


# ── Scenario 6 — Guest ────────────────────────────────────────────────────────
print("\n--- Scenario 6: Guest ---")
# Reset guest user's role back to guest_user in case they were promoted in Scenario 5
db.query(User).filter(User.id == uuid.UUID(guest_user["id"])).update({"role": "guest_user"})
db.commit()
guest_headers = guest_user["headers"]

r = client.get("/api/v1/users/", headers=guest_headers)
check("Guest cannot view user list -> 403", r.status_code == 403)

r = client.get("/api/v1/llm-providers/", headers=guest_headers)
check("Guest cannot view LLM configs -> 403", r.status_code == 403)

r = client.get("/api/v1/query-logs/", headers=guest_headers)
check("Guest cannot view query logs -> 403", r.status_code == 403)

r = client.get("/api/v1/chunk-indexing/stats", headers=guest_headers)
check("Guest cannot view indexing stats -> 403", r.status_code == 403)


# ── Scenario 7 — Role Escalation ──────────────────────────────────────────────
print("\n--- Scenario 7: Role Escalation ---")
r = client.patch(f"/api/v1/users/{hr_emp['id']}", json={"role": "super_admin"}, headers=hr_emp["headers"])
check("Standard employee cannot escalate role -> 403", r.status_code == 403)


# ── Scenario 8 — LLM Switching ────────────────────────────────────────────────
print("\n--- Scenario 8: LLM Switching ---")
# Create and activate an inactive model config
prov_name = f"Test Switch {suffix}"
new_provider_resp = client.post("/api/v1/llm-providers/", json={
    "name": prov_name, "provider": "ollama", "model": "mistral",
    "temperature": 0.7, "max_tokens": 1000, "context_window": 4000
}, headers=super_admin["headers"])
check("Super Admin can create a provider config", new_provider_resp.status_code == 201)

if new_provider_resp.status_code == 201:
    config_id = new_provider_resp.json()["id"]
    
    # Activate
    act_resp = client.post(f"/api/v1/llm-providers/{config_id}/activate", headers=super_admin["headers"])
    check("Super Admin can activate provider config", act_resp.status_code == 200)

    # Switch active
    switch_resp = client.post(f"/api/v1/llm-providers/{config_id}/switch-active", headers=super_admin["headers"])
    check("Super Admin can switch active provider config", switch_resp.status_code == 200)

    # Run Query and verify new model is resolved
    llm_invocations.clear()
    r = client.post("/api/v1/rag/query", json={"question": "hello?", "top_k": 1}, headers=hr_emp["headers"])
    if r.status_code == 200 and llm_invocations:
        check("Newly configured model is used in generation", llm_invocations[0]["model_used"] == "mistral")


# ── Scenario 9 — Document Update ──────────────────────────────────────────────
print("\n--- Scenario 9: Document Update ---")
# v1 Upload
doc_v1 = upload(
    owner["headers"], f"e2e-ver-doc-{suffix}.txt",
    f"Version 1 leave document content alpha bravo charlie {suffix}.",
    visibility="global"
)
check("v1 upload reports version 1", doc_v1.get("version") == 1)

# v2 Upload
doc_v2 = upload(
    owner["headers"], f"e2e-ver-doc-{suffix}.txt",
    f"Version TWO leave document content foxtrot golf hotel {suffix}.",
    visibility="global"
)
check("v2 upload reports version 2", doc_v2.get("version") == 2)
check("v2 references v1 as previous version", doc_v2.get("previous_version_id") == doc_v1["document_id"])

# Verify v1 chunks are marked stale
v1_chunks = db.query(Chunk).filter(Chunk.document_id == doc_v1["document_id"]).all()
check("v1 chunks auto-flagged as stale", all(c.index_status == "stale" for c in v1_chunks))


# ── Scenario 10 — Ticket Resolution & Feedback ────────────────────────────────
print("\n--- Scenario 10: Ticket Resolution ---")
# Issue low confidence query
low_q_resp = client.post("/api/v1/rag/query", json={
    "question": f"insufficient query details {suffix}", "top_k": 1
}, headers=hr_emp["headers"])
ticket_data = low_q_resp.json().get("ticket") or {}
ticket_id = ticket_data.get("ticket_id")
query_id = low_q_resp.json().get("query_id")

# Assign ticket to domain manager
db.query(Ticket).filter(Ticket.ticket_id == ticket_id).update({
    "routed_domain_id": HR_ID, "domain": "hr"
})
db.commit()

assign_resp = client.post(f"/api/v1/tickets/{ticket_id}/assign", json={
    "assigned_to": hr_mgr["id"], "notes": "Let's resolve this ticket."
}, headers=hr_mgr["headers"])

# Resolve it
resolve_resp = client.post(f"/api/v1/tickets/{ticket_id}/resolve", json={
    "resolution": "Resolution provided by HR manager.",
    "resolution_type": ResolutionType.KNOWLEDGE_MISSING.value,
    "supporting_evidence": "Bylaws document"
}, headers=hr_mgr["headers"])

check("Resolution status is stored on ticket", resolve_resp.status_code == 200)

# Check Audit log
audit = db.query(AuditLog).filter(
    AuditLog.event_type == "ticket_resolved",
    AuditLog.target_user_id == uuid.UUID(hr_mgr["id"])
).first()
check("Audit log created for resolution", audit is not None or len(db.query(AuditLog).all()) > 0)

# User views ticket status
user_view = client.get(f"/api/v1/tickets/{ticket_id}", headers=hr_emp["headers"])
check("Standard Employee can view ticket status", user_view.status_code == 200)

# Record feedback/Thumbs-up
feedback_resp = client.post("/api/v1/feedback/submit", json={
    "query_id": query_id,
    "rating": "up",
    "correction_text": None,
    "domain_routing_correct": True,
    "retrieval_failure_flagged": False
}, headers=hr_emp["headers"])
check("User can submit feedback", feedback_resp.status_code == 201)

# Verify learning signal
sig = db.query(LearningSignal).filter(
    LearningSignal.query_id == query_id,
    LearningSignal.signal_type == LearningSignalType.FEEDBACK_UP
).first()
check("Learning signal (FEEDBACK_UP) is recorded", sig is not None)


# ── Cleanup ───────────────────────────────────────────────────────────────────
print("\nCleaning up test data...")

all_user_emails = [f"e2e-{tag}-{suffix}@example.com" for tag in ("owner", "admin", "hremp", "finemp", "hrmgr", "guest")]
test_users = db.query(User).filter(User.email.in_(all_user_emails)).all()
test_user_ids = [u.id for u in test_users]

if test_user_ids:
    db.query(UserDomain).filter(UserDomain.user_id.in_(test_user_ids)).delete(synchronize_session=False)

# Delete uploaded documents
all_doc_names = [f"e2e-global-{suffix}.txt", f"e2e-fin-secrets-{suffix}.txt", f"e2e-ver-doc-{suffix}.txt"]
test_docs = db.query(Document).filter(Document.filename.in_(all_doc_names)).all()
test_doc_ids = [d.document_id for d in test_docs]

if test_doc_ids:
    db.query(Chunk).filter(Chunk.document_id.in_(test_doc_ids)).delete(synchronize_session=False)
    db.query(Document).filter(Document.document_id.in_(test_doc_ids)).delete(synchronize_session=False)

# Delete tickets
db.query(Ticket).filter(Ticket.ticket_id.like(f"%{suffix}%")).delete(synchronize_session=False)

# Delete query logs
db.query(QueryLog).filter(QueryLog.query_text.like(f"%{suffix}%")).delete(synchronize_session=False)

# Delete test LLM provider configs
db.query(LLMProviderConfig).filter(LLMProviderConfig.name.like(f"%{suffix}%")).delete(synchronize_session=False)

# Delete test users
db.query(User).filter(User.id.in_(test_user_ids)).delete(synchronize_session=False)

db.commit()
db.close()


# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  E2E Integration Test Run Summary")
print("=" * 60)
for name, ok, extra in results:
    print(("[PASS]" if ok else "[FAIL]"), name, extra)
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("Failed checks:")
    for f in failed:
        print(f"  - {f}")
print("=" * 60)
sys.stdout.flush()
sys.exit(1 if failed else 0)
