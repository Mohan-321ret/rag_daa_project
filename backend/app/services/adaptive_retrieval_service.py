"""
Adaptive Retrieval Engine  –  Phase 8 Module 6 (Orchestrator)
------------------------------------------------------------------
Ties the Router (Step: choose a route) to the three retrieval backends and,
for the hybrid route, to the Rank Results step:

  Question ─→ Router ─→ Choose Retrieval
                          ├─ Fact                → Vector    (vector_store)
                          ├─ Exact Policy Number  → BM25      (bm25_retriever)
                          ├─ Relationship         → Graph     (graph_retriever)
                          └─ Complex              → Hybrid    (BM25 + Vector + Graph
                                                                → hybrid_ranker RRF)

Entry point: adaptive_retrieve(db, analysis, top_k, access_ctx, document_id=None)
Consumed by rag_service.answer_question, which already has the Phase 7
QueryAnalysis computed and just needs ranked chunks back in a uniform shape.

Domain-Aware Chunk Access Control: `access_ctx` is REQUIRED, not optional —
a security-critical filter should never be silently skippable by a caller
forgetting a keyword argument. Each backend applies a fast in-loop filter
using whatever metadata it already has on hand (see chunk_access_service.py's
docstring for why this two-layer design exists); `adaptive_retrieve` then
applies the authoritative app.services.chunk_access_service.filter_authorized_results
pass on the final result list, unconditionally, regardless of which route
produced it. No code path in this module returns chunks that skip that call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.bm25_retriever import get_bm25_store
from app.services.chunk_access_service import ChunkAccessContext, filter_authorized_results
from app.services.graph_retriever import get_graph_retriever
from app.services.hybrid_ranker import reciprocal_rank_fusion
from app.services.query_intelligence_service import QueryAnalysis
from app.services.retrieval_router import RouteDecision, decide_route
from app.services.storage_service import StorageService
from app.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveRetrievalResult:
    route: RouteDecision
    results: List[dict] = field(default_factory=list)
    route_counts: dict = field(default_factory=dict)  # {"vector": n, "bm25": n, "graph": n}


def _vector_results(
    query: str, top_k: int, document_id: Optional[str], access_ctx: ChunkAccessContext,
) -> List[dict]:
    store = get_vector_store()
    fetch_k = top_k * 3 if document_id else top_k
    raw = store.search(
        query, top_k=min(fetch_k, max(store.total, 1)),
        filter_fn=access_ctx.as_filter_fn(),
    )
    out = []
    for r in raw:
        meta = r.get("metadata", {})
        doc_id = meta.get("document_id")
        if document_id and doc_id != document_id:
            continue
        out.append({
            "document_id": doc_id,
            "chunk_index": meta.get("chunk_index"),
            "text": r.get("text") or "",
            "score": r.get("score", 0.0),
            "metadata": meta,
            "domain_id": meta.get("domain_id"),
            "visibility": meta.get("visibility"),
            "source": "vector",
        })
        if len(out) >= top_k:
            break
    return out


def _bm25_results(
    db: Session, query: str, top_k: int, document_id: Optional[str], access_ctx: ChunkAccessContext,
) -> List[dict]:
    store = get_bm25_store()
    hits = store.search(
        db, query, top_k=top_k * 3 if document_id else top_k,
        filter_fn=access_ctx.as_filter_fn(),
    )
    out = []
    for h in hits:
        if document_id and h.document_id != document_id:
            continue
        out.append({
            "document_id": h.document_id,
            "chunk_index": h.chunk_index,
            "text": h.text,
            "score": h.score,
            "metadata": {"document_id": h.document_id, "chunk_index": h.chunk_index},
            "domain_id": h.domain_id,
            "visibility": h.visibility,
            "source": "bm25",
        })
        if len(out) >= top_k:
            break
    return out


def _graph_results(
    db: Session, analysis: QueryAnalysis, top_k: int, document_id: Optional[str],
    access_ctx: ChunkAccessContext,
) -> List[dict]:
    entity_texts = [e.text for e in analysis.entities if e.text.strip()]
    if not entity_texts:
        return []

    retriever = get_graph_retriever()
    # Over-fetch further than usual: unlike vector/BM25, Neo4j's own query
    # has no authorization awareness (its WHERE clause can't see Postgres
    # grants/ownership) — filtering here happens entirely in this loop
    # against the freshly-fetched Chunk row's domain_id/visibility, so we
    # need a wider candidate pool to still land on `top_k` authorized hits.
    fetch_k = top_k * (5 if document_id else 4)
    hits = retriever.search_related_chunks(entity_texts, top_k=fetch_k)

    storage = StorageService(db)
    out = []
    for h in hits:
        if document_id and h.document_id != document_id:
            continue
        chunk = storage.get_chunk_by_index(h.document_id, h.chunk_index)
        if chunk is None:
            continue
        if not access_ctx.is_authorized(h.document_id, chunk.domain_id, chunk.visibility):
            continue
        out.append({
            "document_id": h.document_id,
            "chunk_index": h.chunk_index,
            "text": chunk.text,
            "score": 1.0 / h.rank,   # rank-derived pseudo-score (graph has no cosine/BM25 scale)
            "metadata": {
                "document_id": h.document_id,
                "chunk_index": h.chunk_index,
                "matched_entity": h.matched_entity,
                "related_entities": h.related_entities,
            },
            "domain_id": str(chunk.domain_id) if chunk.domain_id else None,
            "visibility": chunk.visibility,
            "source": "graph",
        })
        if len(out) >= top_k:
            break
    return out


def adaptive_retrieve(
    db: Session,
    analysis: QueryAnalysis,
    top_k: int,
    access_ctx: ChunkAccessContext,
    document_id: Optional[str] = None,
) -> AdaptiveRetrievalResult:
    """
    Route *analysis*'s query to the right retrieval backend(s) and return
    ranked chunks in a uniform shape:
        {document_id, chunk_index, text, score, metadata, source(s)}

    Every chunk in the returned list has passed BOTH the fast in-backend
    filter and the final chunk_access_service.filter_authorized_results
    authoritative gate — see this module's docstring.
    """
    route = decide_route(analysis, db=db)   # Phase 12: may escalate to "hybrid" on feedback
    query = analysis.normalized_query

    # Phase 12 – Module 10 (Improve Retrieval): widen top_k for a route with a
    # confirmed history of poor satisfaction, so it pulls in more candidate
    # evidence rather than repeating whatever was too narrow before.
    from app.services.routing_improvement_service import suggest_topk_multiplier
    multiplier = suggest_topk_multiplier(db, route.route, analysis.intent.intent)
    if multiplier > 1.0:
        top_k = min(int(round(top_k * multiplier)), settings.learning_topk_boost_max)

    if route.route == "vector":
        results = _vector_results(query, top_k, document_id, access_ctx)
        counts = {"vector": len(results)}

    elif route.route == "bm25":
        results = _bm25_results(db, query, top_k, document_id, access_ctx)
        counts = {"bm25": len(results)}

    elif route.route == "graph":
        results = _graph_results(db, analysis, top_k, document_id, access_ctx)
        counts = {"graph": len(results)}
        if not results:
            # No graph data (Neo4j down, or entities never indexed) – fall back
            # to vector search rather than returning nothing to the user.
            logger.info("[AdaptiveRetrieval] Graph route empty – falling back to vector.")
            results = _vector_results(query, top_k, document_id, access_ctx)
            counts["vector_fallback"] = len(results)

    else:  # hybrid
        vec = _vector_results(query, top_k, document_id, access_ctx)
        bm25 = _bm25_results(db, query, settings.bm25_top_k, document_id, access_ctx)
        graph = _graph_results(db, analysis, settings.graph_top_k, document_id, access_ctx)
        counts = {"vector": len(vec), "bm25": len(bm25), "graph": len(graph)}

        lists = {k: v for k, v in {"vector": vec, "bm25": bm25, "graph": graph}.items() if v}
        results = reciprocal_rank_fusion(lists, top_k=top_k) if lists else []
        for r in results:
            r.setdefault("source", "+".join(r.get("sources", [])) or "hybrid")

    # ── Authorization Filter (authoritative) ────────────────────────────────────
    # The hard guarantee: re-verify against Postgres truth regardless of what
    # each backend's fast filter already did, regardless of route.
    pre_filter_count = len(results)
    results = filter_authorized_results(db, results, access_ctx)
    if len(results) != pre_filter_count:
        counts["authorization_filtered"] = pre_filter_count - len(results)

    logger.info(
        "[AdaptiveRetrieval] route=%s reason='%s' results=%d breakdown=%s",
        route.route, route.reason, len(results), counts,
    )
    return AdaptiveRetrievalResult(route=route, results=results, route_counts=counts)
