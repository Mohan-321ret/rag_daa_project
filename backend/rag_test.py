"""
Phase 5 RAG Pipeline Test Script
---------------------------------
Tests the full RAG pipeline end-to-end:
  1. Check RAG status (index size)
  2. Send a test question
  3. Print answer + sources

Usage:
    python rag_test.py
    python rag_test.py --question "What is machine learning?"
    python rag_test.py --doc DOC_001 --question "Summarise this document"
"""
import argparse
import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000/api/v1"


def _post(endpoint: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"❌ HTTP {e.code}: {body}")
        sys.exit(1)


def _get(endpoint: str) -> dict:
    req = urllib.request.Request(f"{BASE_URL}{endpoint}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"❌ HTTP {e.code}: {body}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Phase 5 RAG Pipeline Test")
    parser.add_argument("--question", "-q", default="What is the main topic of the uploaded documents?")
    parser.add_argument("--doc", "-d", default=None, help="Filter by document_id (optional)")
    parser.add_argument("--top_k", "-k", type=int, default=5)
    args = parser.parse_args()

    print("=" * 60)
    print("  Phase 5 – RAG Pipeline Test")
    print("=" * 60)

    # ── 1. Status check ─────────────────────────────────────────────────────
    print("\n📊 Checking RAG status...")
    status = _get("/rag/status")
    print(f"   Status         : {status['status']}")
    print(f"   Indexed chunks : {status['total_indexed_chunks']}")
    print(f"   LLM provider   : {status['llm_provider']}")
    print(f"   Embed model    : {status['embedding_model']}")
    print(f"   Message        : {status['message']}")

    if status["total_indexed_chunks"] == 0:
        print("\n⚠️  No chunks indexed. Upload a document first:")
        print("   POST /api/v1/documents/upload")
        sys.exit(0)

    # ── 2. RAG query ────────────────────────────────────────────────────────
    print(f"\n🤔 Question: {args.question}")
    if args.doc:
        print(f"   Filtered to doc: {args.doc}")
    print("   Sending to RAG pipeline...\n")

    payload = {
        "question": args.question,
        "top_k": args.top_k,
    }
    if args.doc:
        payload["document_id"] = args.doc

    result = _post("/rag/query", payload)

    # ── 3. Print results ─────────────────────────────────────────────────────
    print("─" * 60)
    print("💬 ANSWER:")
    print(result["answer"])
    print("─" * 60)
    print(f"\n📈 Stats:")
    print(f"   Retrieved chunks : {result['retrieved_chunks']}")
    print(f"   Total indexed    : {result['total_indexed']}")
    print(f"   LLM provider     : {result['provider']}")

    print(f"\n📚 Sources ({len(result['sources'])} chunks):")
    for i, src in enumerate(result["sources"], 1):
        print(f"\n  [{i}] {src['document_id']}  chunk={src['chunk_index']}  score={src['score']:.4f}")
        print(f"       {src['text_preview'][:120]}…")

    print("\n✅ RAG Pipeline test complete!")


if __name__ == "__main__":
    main()
