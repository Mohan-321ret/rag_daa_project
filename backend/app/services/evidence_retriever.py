"""
Evidence Retriever  –  Phase 11 Module 9 (Step 2: Retrieve Evidence Again)
------------------------------------------------------------------------------
Independently re-retrieves evidence for each extracted CLAIM, rather than
reusing whatever chunks Phase 9's Context Fusion happened to compress into
the final prompt. This matters because compression can trim away the exact
sentence that would have kept the LLM honest, and because querying by the
claim's own text (not the original question) surfaces evidence specific
to that one fact instead of the question's overall topic.

Combines FAISS vector search (semantic) with BM25 (exact term/number
matching — important here since "20 days" and "25 days" are semantically
almost identical but factually different) via Phase 8's RRF fusion.

Domain-Aware Chunk Access Control: this is a SEPARATE retrieval path from
app.services.adaptive_retrieval_service — evidence is re-retrieved
independently of the main answer's context (see module docstring above),
which means it independently needs the SAME authorization treatment.
Without it, a "correction" could quote or contradict-flag a claim using a
chunk the requesting user isn't authorized to see, leaking its content (or
even just its existence) through the verification verdict. `access_ctx` is
REQUIRED on retrieve_evidence() for the same "never silently skippable"
reason app.services.adaptive_retrieval_service.adaptive_retrieve requires it.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.bm25_retriever import get_bm25_store
from app.services.chunk_access_service import ChunkAccessContext, filter_authorized_results
from app.services.hybrid_ranker import reciprocal_rank_fusion
from app.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def _vector_hits(query: str, top_k: int, access_ctx: ChunkAccessContext) -> List[dict]:
    store = get_vector_store()
    if store.total == 0:
        return []
    raw = store.search(query, top_k=min(top_k, store.total), filter_fn=access_ctx.as_filter_fn())
    out = []
    for r in raw:
        meta = r.get("metadata", {})
        doc_id = meta.get("document_id")
        if not doc_id:
            continue
        out.append({
            "document_id": doc_id,
            "chunk_index": meta.get("chunk_index"),
            "text": r.get("text") or "",
            "score": r.get("score", 0.0),
            "metadata": meta,
        })
    return out


def _bm25_hits(db: Session, query: str, top_k: int, access_ctx: ChunkAccessContext) -> List[dict]:
    store = get_bm25_store()
    hits = store.search(db, query, top_k=top_k, filter_fn=access_ctx.as_filter_fn())
    return [
        {
            "document_id": h.document_id,
            "chunk_index": h.chunk_index,
            "text": h.text,
            "score": h.score,
            "metadata": {"document_id": h.document_id, "chunk_index": h.chunk_index},
        }
        for h in hits
    ]


def _document_hits(db: Session, document_id: str) -> List[dict]:
    """
    Pull ALL of one document's chunks directly from PostgreSQL. Used instead
    of a global vector/BM25 search-then-filter when evidence must be scoped
    to a single document: a fixed-size fetch_k over a large, ever-growing
    corpus can rank that document's own chunk outside the candidate window
    even though it's the correct evidence, silently turning a real
    contradiction into a false "unverifiable". Going straight to the source
    document is both cheaper and guaranteed not to miss it.
    """
    from app.services.storage_service import StorageService
    chunks = StorageService(db).get_chunks(document_id)
    return [
        {
            "document_id": document_id,
            "chunk_index": c.chunk_index,
            "text": c.text,
            "score": 1.0,
            "metadata": {"document_id": document_id, "chunk_index": c.chunk_index},
        }
        for c in chunks
    ]


def retrieve_evidence(
    db: Session,
    claim_text: str,
    access_ctx: ChunkAccessContext,
    top_k: Optional[int] = None,
    document_id: Optional[str] = None,
) -> List[dict]:
    """
    Independently retrieve the best evidence chunks for *claim_text*
    (typically one sentence from a generated answer), fusing vector + BM25
    results so both semantic and exact-number matches surface.

    Args:
        access_ctx: Required — see this module's docstring. Every path
                    below (document-scoped, vector, BM25) passes through
                    filter_authorized_results before returning.
        document_id: If the original question was scoped to one document
                    (RAGQueryRequest.document_id), evidence must be scoped
                    to it too — otherwise a "correction" could cite a fact
                    from a document the user explicitly excluded. Scoped
                    lookups go straight to that document's chunks in
                    PostgreSQL rather than filtering a global top-k search
                    (see _document_hits).
    """
    top_k = top_k if top_k is not None else settings.verification_evidence_top_k
    if not claim_text or not claim_text.strip():
        return []

    if document_id:
        hits = _document_hits(db, document_id)
        hits = filter_authorized_results(db, hits, access_ctx)
        logger.debug(
            "[EvidenceRetriever] claim='%s...' doc_filter=%s -> %d chunk(s) (direct lookup)",
            claim_text[:60], document_id, len(hits),
        )
        return hits

    vector = _vector_hits(claim_text, top_k, access_ctx)
    bm25 = _bm25_hits(db, claim_text, top_k, access_ctx)

    lists = {k: v for k, v in {"vector": vector, "bm25": bm25}.items() if v}
    if not lists:
        return []

    fused = reciprocal_rank_fusion(lists, top_k=top_k)
    fused = filter_authorized_results(db, fused, access_ctx)
    logger.debug(
        "[EvidenceRetriever] claim='%s...' -> %d evidence chunk(s)",
        claim_text[:60], len(fused),
    )
    return fused
