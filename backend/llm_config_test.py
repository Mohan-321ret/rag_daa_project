"""
Admin Panel: LLM and Model Switching test suite (real-DB TestClient).

Covers: the provider registry, viewing configured providers, add/configure/
activate/deactivate/switch-active/test-connection, RBAC gating of
LLM_VIEW (read) vs LLM_CONFIGURE (write — platform_owner/super_admin only,
per the existing Phase 2 matrix), audit logging, and — the security-critical
part — that a configured API key's actual VALUE never appears anywhere in
an API response, only the name of the env var that holds it.

Ends by switching the active model back to the original seeded default and
deactivating the test-created config, so later test runs (and any other
test file's real /rag/query calls) aren't left pointed at a throwaway
config with no working credentials.
"""
import os
import time
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.llm_provider import LLMProviderConfig

client = TestClient(app)
db = SessionLocal()
suffix = uuid.uuid4().hex[:8]
results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(("PASS" if cond else "FAIL"), name, extra)


def make_user(role: str, tag: str):
    email = f"llmcfg-{tag}-{suffix}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "testpass123"})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    db.query(User).filter(User.id == user_id).update({"role": role})
    db.commit()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "testpass123"})
    token = login.json()["access_token"]
    return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


owner = make_user("platform_owner", "owner")
domain_mgr = make_user("domain_manager", "domainmgr")   # LLM_VIEW only, per the matrix
client_user = make_user("client_user", "clientuser")     # neither

SECRET_ENV_VAR = f"LLMCFG_TEST_SECRET_{suffix.upper()}"
SECRET_VALUE = f"sk-supersecret-{suffix}-do-not-leak"
os.environ[SECRET_ENV_VAR] = SECRET_VALUE

# ── Registry ─────────────────────────────────────────────────────────────────
r = client.get("/api/v1/llm-providers/registry", headers=owner["headers"])
check("registry reachable", r.status_code == 200, r.text[:150])
providers = r.json()["providers"]
check("registry includes ollama/openai/groq (not hardcoded elsewhere, but these ARE registered)",
      {"ollama", "openai", "groq"} <= set(providers), providers)

r = client.get("/api/v1/llm-providers/registry", headers=client_user["headers"])
check("CLIENT_USER (no LLM_VIEW) cannot view registry -> 403", r.status_code == 403)

# ── View configured providers ───────────────────────────────────────────────
r = client.get("/api/v1/llm-providers/", headers=owner["headers"])
check("list providers reachable", r.status_code == 200, r.text[:150])
seeded = next((p for p in r.json()["providers"] if p["is_current"]), None)
check("exactly one seeded/current config exists on a fresh-ish DB", seeded is not None, r.json())
original_active_id = seeded["id"] if seeded else None

r = client.get("/api/v1/llm-providers/", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER (has LLM_VIEW) can list providers", r.status_code == 200)

r = client.get("/api/v1/llm-providers/", headers=client_user["headers"])
check("CLIENT_USER (no LLM_VIEW) cannot list providers -> 403", r.status_code == 403)

# ── Add provider ─────────────────────────────────────────────────────────────
r = client.post("/api/v1/llm-providers/", json={
    "name": f"Test OpenAI {suffix}", "provider": "openai", "model": "gpt-4o-mini",
    "api_key_env_var": SECRET_ENV_VAR, "temperature": 0.5, "max_tokens": 500, "context_window": 8000,
}, headers=domain_mgr["headers"])
check("DOMAIN_MANAGER (no LLM_CONFIGURE) cannot add a provider -> 403", r.status_code == 403)

r = client.post("/api/v1/llm-providers/", json={
    "name": f"Test OpenAI {suffix}", "provider": "totally_bogus_provider", "model": "x",
}, headers=owner["headers"])
check("unregistered provider key -> 422", r.status_code == 422, r.text[:150])

r = client.post("/api/v1/llm-providers/", json={
    "name": f"Test OpenAI {suffix}", "provider": "openai", "model": "gpt-4o-mini",
    "api_key_env_var": SECRET_ENV_VAR, "temperature": 0.5, "max_tokens": 500, "context_window": 8000,
}, headers=owner["headers"])
check("PLATFORM_OWNER can add a provider", r.status_code == 201, r.text[:200])
new_config = r.json()
new_id = new_config["id"]
check("created config starts inactive, not current", new_config["status"] == "inactive" and new_config["is_current"] is False)
check("response carries the env var NAME, never the secret value", new_config["api_key_env_var"] == SECRET_ENV_VAR)
check("SECRET VALUE never appears anywhere in the create response", SECRET_VALUE not in r.text)
check("api_key_configured reflects the env var actually being set", new_config["api_key_configured"] is True)

r = client.post("/api/v1/llm-providers/", json={
    "name": f"Test OpenAI {suffix}", "provider": "groq", "model": "llama3-8b-8192",
}, headers=owner["headers"])
check("duplicate name -> 409", r.status_code == 409)

# ── Configure model ──────────────────────────────────────────────────────────
r = client.patch(f"/api/v1/llm-providers/{new_id}", json={"temperature": 0.2, "max_tokens": 1000}, headers=domain_mgr["headers"])
check("DOMAIN_MANAGER cannot configure a model -> 403", r.status_code == 403)

r = client.patch(f"/api/v1/llm-providers/{new_id}", json={"temperature": 0.2, "max_tokens": 1000}, headers=owner["headers"])
check("PLATFORM_OWNER can configure a model", r.status_code == 200 and r.json()["temperature"] == 0.2 and r.json()["max_tokens"] == 1000, r.text[:200])
check("SECRET VALUE never appears anywhere in the configure response", SECRET_VALUE not in r.text)

# ── Switch-active before activation is refused ──────────────────────────────
r = client.post(f"/api/v1/llm-providers/{new_id}/switch-active", headers=owner["headers"])
check("cannot switch to a not-yet-activated config -> 400", r.status_code == 400, r.text[:150])

# ── Activate model ───────────────────────────────────────────────────────────
r = client.post(f"/api/v1/llm-providers/{new_id}/activate", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER cannot activate a model -> 403", r.status_code == 403)

r = client.post(f"/api/v1/llm-providers/{new_id}/activate", headers=owner["headers"])
check("PLATFORM_OWNER can activate a model", r.status_code == 200 and r.json()["status"] == "active", r.text[:150])

# ── Switch active model ──────────────────────────────────────────────────────
r = client.post(f"/api/v1/llm-providers/{new_id}/switch-active", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER cannot switch the active model -> 403", r.status_code == 403)

r = client.post(f"/api/v1/llm-providers/{new_id}/switch-active", headers=owner["headers"])
check("PLATFORM_OWNER can switch the active model", r.status_code == 200 and r.json()["provider"] == "openai", r.text[:200])

r = client.get(f"/api/v1/llm-providers/{new_id}", headers=owner["headers"])
check("switched config is now is_current", r.status_code == 200 and r.json()["is_current"] is True)

if original_active_id:
    r = client.get(f"/api/v1/llm-providers/{original_active_id}", headers=owner["headers"])
    check("previously-active config lost is_current after the switch", r.status_code == 200 and r.json()["is_current"] is False)

# ── RAG pipeline automatically picks up the switch ──────────────────────────
r = client.get("/api/v1/llm/models", headers=owner["headers"])
check("GET /llm/models reflects the newly-switched provider (no stale .env snapshot)", r.status_code == 200 and r.json()["provider"] == "openai", r.text[:200])

# ── Cannot deactivate the currently-active config ───────────────────────────
r = client.post(f"/api/v1/llm-providers/{new_id}/deactivate", headers=owner["headers"])
check("cannot deactivate the currently-active config -> 400", r.status_code == 400, r.text[:150])

# ── Test connection: deterministic failure path (bad env var reference) ────
r = client.post("/api/v1/llm-providers/", json={
    "name": f"Test Bad Key {suffix}", "provider": "openai", "model": "gpt-4o-mini",
    "api_key_env_var": f"LLMCFG_TEST_NOT_SET_{suffix.upper()}",
}, headers=owner["headers"])
check("created a second test config for the bad-key test-connection case", r.status_code == 201, r.text[:150])
bad_key_id = r.json()["id"]

r = client.post(f"/api/v1/llm-providers/{new_id}/test-connection", headers=domain_mgr["headers"])
check("DOMAIN_MANAGER cannot trigger test-connection -> 403", r.status_code == 403)

r = client.post(f"/api/v1/llm-providers/{bad_key_id}/test-connection", headers=owner["headers"])
check("test-connection reachable and returns a structured result", r.status_code == 200, r.text[:200])
tc = r.json()
check("test-connection fails cleanly when the referenced env var isn't set", tc["success"] is False and "not set" in tc["message"].lower(), tc)

# ── Switch back to the original config + clean up ───────────────────────────
if original_active_id:
    r = client.post(f"/api/v1/llm-providers/{original_active_id}/switch-active", headers=owner["headers"])
    check("switched active model back to the original seeded config", r.status_code == 200, r.text[:150])

r = client.post(f"/api/v1/llm-providers/{new_id}/deactivate", headers=owner["headers"])
check("can deactivate the test config once it's no longer current", r.status_code == 200 and r.json()["status"] == "inactive", r.text[:150])

# ── Audit log ────────────────────────────────────────────────────────────────
for event_type in ("llm_provider_added", "llm_provider_configured", "llm_provider_activated", "llm_switched", "llm_provider_deactivated"):
    r = client.get("/api/v1/audit-logs/", params={"event_type": event_type, "limit": 200}, headers=owner["headers"])
    check(f"audit log recorded {event_type} events", r.status_code == 200 and r.json()["total"] >= 1, r.text[:150])

# ── Cleanup ──────────────────────────────────────────────────────────────────
db.query(LLMProviderConfig).filter(LLMProviderConfig.id.in_([new_id, bad_key_id])).delete(synchronize_session=False)
db.query(User).filter(User.email.like(f"llmcfg-%-{suffix}@example.com")).delete(synchronize_session=False)
db.commit()
db.close()
del os.environ[SECRET_ENV_VAR]

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
