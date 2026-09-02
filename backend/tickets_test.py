"""Ad-hoc test for the Automatic Ticketing module (real-DB TestClient)."""
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.base import init_db
from app.main import app
from app.services.ticket_service import maybe_create_ticket
from app.db.database import SessionLocal
from app.models.ticket import Ticket
from app.models.user import User

init_db()  # ensure tickets table exists

client = TestClient(app)
db = SessionLocal()
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


# RBAC Foundation: ticket endpoints now require TICKET_VIEW (+ TICKET_ASSIGN/
# TICKET_RESOLVE for PATCH). Register a reviewer-tier user for this run.
_suffix = uuid.uuid4().hex[:8]
_email = f"tickets-test-reviewer-{_suffix}@example.com"
client.post("/api/v1/auth/register", json={"email": _email, "password": "testpass123"})
db.query(User).filter(User.email == _email).update({"role": "domain_manager"})
db.commit()
_login = client.post("/api/v1/auth/login", json={"email": _email, "password": "testpass123"})
AUTH = {"Authorization": f"Bearer {_login.json()['access_token']}"}


settings.ticketing_enabled = True
settings.ticket_confidence_threshold = 0.5
MARKER = "tickets-test what is the leave policy"

# 0. Clean slate for the marker query
db.query(Ticket).filter(Ticket.query_text.ilike(f"%tickets-test%")).delete(synchronize_session=False)
db.commit()

# 1. High confidence -> no ticket
t = maybe_create_ticket(db, query_id="QRY_TEST1", query_text=MARKER,
                        answer_text="a", confidence_score=0.9)
check("high confidence creates no ticket", t is None)

# 2. Low confidence -> ticket raised, default department
t = maybe_create_ticket(db, query_id="QRY_TEST2", query_text=MARKER,
                        answer_text="uncertain answer", confidence_score=0.3,
                        hallucinations_detected=2,
                        source_document_ids=["DOC_DOESNOTEXIST"])
check("low confidence raises ticket", t is not None and t.ticket_id.startswith("TKT_"))
check("department falls back to General", t is not None and t.department == "General")

# 3. Same query again while open -> dedup bump, keeps worst confidence
t2 = maybe_create_ticket(db, query_id="QRY_TEST3", query_text=MARKER.upper(),
                         answer_text="uncertain answer", confidence_score=0.4)
check("duplicate open query bumps occurrence", t2 is not None
      and t2.ticket_id == t.ticket_id and t2.occurrence_count == 2)
check("keeps worst confidence", t2 is not None and t2.confidence_score == 0.3)

# 4. Disabled / no score -> no ticket
settings.ticketing_enabled = False
check("disabled creates no ticket",
      maybe_create_ticket(db, query_id=None, query_text=MARKER, answer_text=None,
                          confidence_score=0.1) is None)
settings.ticketing_enabled = True
check("missing score creates no ticket",
      maybe_create_ticket(db, query_id=None, query_text=MARKER, answer_text=None,
                          confidence_score=None) is None)

tid = t.ticket_id

# 5. API: list / stats / detail
r = client.get("/api/v1/tickets/", params={"status": "open"}, headers=AUTH)
check("list open tickets", r.status_code == 200
      and any(x["ticket_id"] == tid for x in r.json()["tickets"]))
r = client.get("/api/v1/tickets/", params={"status": "bogus"}, headers=AUTH)
check("bad status filter 422", r.status_code == 422)
r = client.get("/api/v1/tickets/stats", headers=AUTH)
check("stats endpoint", r.status_code == 200 and r.json()["open"] >= 1
      and "General" in r.json()["by_department"])
r = client.get(f"/api/v1/tickets/{tid}", headers=AUTH)
check("detail endpoint", r.status_code == 200
      and r.json()["source_document_ids"] == ["DOC_DOESNOTEXIST"]
      and r.json()["hallucinations_detected"] == 2)
check("detail 404", client.get("/api/v1/tickets/TKT_NOPE", headers=AUTH).status_code == 404)

# 6. API: review lifecycle open -> in_review -> resolved
r = client.patch(f"/api/v1/tickets/{tid}",
                 json={"status": "in_review", "assigned_to": "hr.official@example.com"}, headers=AUTH)
check("claim ticket", r.status_code == 200 and r.json()["status"] == "in_review")
r = client.patch(f"/api/v1/tickets/{tid}",
                 json={"status": "resolved", "reviewer_notes": "Verified against policy doc",
                       "corrected_answer": "Leave policy is 25 days."}, headers=AUTH)
check("resolve ticket", r.status_code == 200 and r.json()["status"] == "resolved"
      and r.json()["resolved_at"] is not None
      and r.json()["corrected_answer"] == "Leave policy is 25 days.")

# 7. Resolved ticket no longer dedups -> new low-confidence query opens a fresh ticket
t3 = maybe_create_ticket(db, query_id="QRY_TEST4", query_text=MARKER,
                         answer_text="still uncertain", confidence_score=0.2)
check("resolved ticket does not swallow new escalation",
      t3 is not None and t3.ticket_id != tid)

# Cleanup
db.query(Ticket).filter(Ticket.query_text.ilike("%tickets-test%")).delete(synchronize_session=False)
db.query(User).filter(User.email == _email).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
