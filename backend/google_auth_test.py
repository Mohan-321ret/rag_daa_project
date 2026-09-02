"""Ad-hoc test for POST /auth/google (real-DB TestClient, mirrors api_test.py style)."""
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import auth_service

client = TestClient(app)
suffix = uuid.uuid4().hex[:8]
GOOGLE_EMAIL = f"g-{suffix}@example.com"
LOCAL_EMAIL = f"l-{suffix}@example.com"

results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


# 1. Unconfigured -> 503
settings.google_client_id = ""
r = client.post("/api/v1/auth/google", json={"credential": "x"})
check("unconfigured returns 503", r.status_code == 503, r.text[:100])

# 2. Configured but bogus token -> 401
settings.google_client_id = "test-client-id.apps.googleusercontent.com"
r = client.post("/api/v1/auth/google", json={"credential": "not-a-real-token"})
check("invalid token returns 401", r.status_code == 401, r.text[:100])

# 3. Valid (mocked) token, new user -> account created, JWT works on /auth/me
claims = {
    "email": GOOGLE_EMAIL,
    "email_verified": True,
    "name": "Google Test User",
    "picture": "https://example.com/pic.jpg",
    "sub": "1234567890",
}
orig_verify = auth_service.verify_google_id_token
import app.api.auth as auth_api
auth_api.verify_google_id_token = lambda cred: claims

r = client.post("/api/v1/auth/google", json={"credential": "mocked"})
check("mocked google login returns 200", r.status_code == 200, r.text[:200])
body = r.json()
check("user created with google provider", body["user"]["auth_provider"] == "google")
check("picture stored", body["user"]["picture"] == "https://example.com/pic.jpg")

me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
check("issued JWT valid on /auth/me", me.status_code == 200 and me.json()["email"] == GOOGLE_EMAIL)

# 4. Second google login, same email -> same account (no duplicate)
r2 = client.post("/api/v1/auth/google", json={"credential": "mocked"})
check("repeat login reuses account", r2.status_code == 200 and r2.json()["user"]["id"] == body["user"]["id"])

# 5. Google account has no password -> password login must fail
r = client.post("/api/v1/auth/login", json={"email": GOOGLE_EMAIL, "password": "whatever123"})
check("password login on google account fails 401", r.status_code == 401)

# 6. Existing local account links on google sign-in (same email)
r = client.post("/api/v1/auth/register", json={"email": LOCAL_EMAIL, "password": "localpass123"})
check("local register ok", r.status_code == 201)
local_id = r.json()["user"]["id"]
claims["email"] = LOCAL_EMAIL
r = client.post("/api/v1/auth/google", json={"credential": "mocked"})
check("google login links existing local account", r.status_code == 200 and r.json()["user"]["id"] == local_id)
r = client.post("/api/v1/auth/login", json={"email": LOCAL_EMAIL, "password": "localpass123"})
check("local password still works after link", r.status_code == 200)

auth_api.verify_google_id_token = orig_verify

# Cleanup created rows
from app.db.database import SessionLocal
from app.models.user import User
db = SessionLocal()
db.query(User).filter(User.email.in_([GOOGLE_EMAIL, LOCAL_EMAIL])).delete(synchronize_session=False)
db.commit()
db.close()

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
