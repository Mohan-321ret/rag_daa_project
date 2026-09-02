"""
Backend API Self-Test Script
Run: python api_test.py
Requires a running server (`uvicorn app.main:app`) — this script talks HTTP,
it does not import the app.
"""
import urllib.request
import json
import sys
import time
import uuid

BASE_URL = "http://localhost:8000"

# RBAC Foundation: most endpoints below now require a Bearer token. Register
# (or log in as) a throwaway account and attach it to every request.
AUTH_HEADERS = {}

def get(path):
    req = urllib.request.Request(BASE_URL + path, headers=AUTH_HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())

def post_json(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": "application/json", **AUTH_HEADERS},
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())

def post_file(path, filename, content):
    boundary = "----BoundaryXYZ"
    file_part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
    ).encode() + (content.encode() if isinstance(content, str) else content)
    body = file_part + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **AUTH_HEADERS},
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read())

print("=" * 60)
print("BACKEND API SELF-TEST")
print("=" * 60)

print("\n[0] Registering throwaway account for auth...")
try:
    email = f"api-self-test-{uuid.uuid4().hex[:8]}@example.com"
    token_data = post_json("/api/v1/auth/register", {"email": email, "password": "selftestpass123"})
    AUTH_HEADERS["Authorization"] = f"Bearer {token_data['access_token']}"
    print(f"  OK: role={token_data['user']['role']}")
    if token_data["user"]["role"] != "platform_owner":
        print(
            "  NOTE: this account is not PLATFORM_OWNER (an earlier account already "
            "bootstrapped that role on this DB), so document/upload/chunk endpoints "
            "below will 403 unless you promote it manually via PATCH /api/v1/users/{id}."
        )
except Exception as e:
    print("  FAIL:", e)
    sys.exit(1)

# Test 1: Root
print("\n[1] Root (GET /)...")
try:
    data = get("/")
    print("  OK:", data)
except Exception as e:
    print("  FAIL:", e)
    sys.exit(1)

# Test 2: Health
print("\n[2] Health (GET /api/v1/health)...")
try:
    data = get("/api/v1/health")
    print("  Status:", data["status"])
    for svc, st in data["services"].items():
        print(f"     {svc}: {st}")
except Exception as e:
    print("  FAIL:", e)

# Test 3: List documents
print("\n[3] List documents (GET /api/v1/documents/)...")
try:
    data = get("/api/v1/documents/")
    total = data["total"]
    print(f"  Total docs: {total}")
    for d in data["documents"]:
        print(f"     {d['document_id']} | status={d['processing_status']} | words={d['word_count']}")
except Exception as e:
    print("  FAIL:", e)

# Test 4: Upload (async job — see Admin Panel: Data Injection Management)
print("\n[4] Upload test.txt (POST /api/v1/documents/upload)...")
try:
    content = (
        "Artificial Intelligence and Machine Learning\n\n"
        "This is a comprehensive test document for the RAG pipeline. "
        "It covers natural language processing, vector embeddings, and semantic search. "
        "Key concepts include: transformers, attention mechanisms, FAISS indexing, "
        "sentence embeddings, and retrieval-augmented generation (RAG)."
    )
    accepted = post_file("/api/v1/documents/upload", "test_doc.txt", content)
    job_id = accepted.get("job_id")
    print(f"  job_id         : {job_id} (status={accepted.get('status')})")

    job = {}
    deadline = time.time() + 60
    while job_id and time.time() < deadline:
        job = get(f"/api/v1/ingestion-jobs/{job_id}")
        if job.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)

    doc_id = job.get("document_id")
    result = get(f"/api/v1/documents/{doc_id}") if doc_id else {}
    status = result.get("processing_status", "unknown")
    print(f"  job status     : {job.get('status')}")
    print(f"  document_id    : {result.get('document_id')}")
    print(f"  processing_status: {status}")
    print(f"  word_count     : {result.get('word_count')}")

    if doc_id and status == "indexed":
        print(f"\n[5] Chunks for {doc_id}...")
        try:
            chunks = get(f"/api/v1/chunks/{doc_id}")
            print(f"  Total chunks: {chunks['total']}")
        except Exception as e:
            print(f"  FAIL: {e}")
    else:
        print(f"\n[5] Skipping chunks test (status={status})")

except Exception as e:
    print(f"  FAIL: {e}")

# Test 6: Semantic search
print("\n[6] Semantic search (POST /api/v1/chunks/search)...")
try:
    result = post_json("/api/v1/chunks/search", {"query": "machine learning", "top_k": 3})
    print(f"  Total indexed: {result.get('total_indexed')}")
    for r in result.get("results", []):
        print(f"  score={r['score']:.4f} text={str(r.get('text',''))[:50]}...")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n" + "=" * 60)
print("SELF-TEST COMPLETE")
print("=" * 60)
