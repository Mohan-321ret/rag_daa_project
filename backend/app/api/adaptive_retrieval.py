"""
Adaptive Retrieval API Router  –  Phase 8 Module 6
------------------------------------------------------
Endpoint: POST /api/v1/retrieval/route

Standalone access to the Router + retrieval step for inspection/testing –
shows which route (vector/bm25/graph/hybrid) a question was sent down and
why, plus the chunks it retrieved. The same engine runs automatically
inside POST /api/v1/rag/query (Phase 5) to source the LLM's context.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.user import User
from app.schemas.adaptive_retrieval import (
    RetrievalRouteRequest,
    RetrievalRouteResponse,
    RetrievedChunkOut,
    RouteDecisionOut,
)
from app.services.adaptive_retrieval_service import adaptive_retrieve
from app.services.auth_service import current_role, require_permission
from app.services.chunk_access_service import build_chunk_access_context
from app.services.query_intelligence_service import analyze_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieval", tags=["Adaptive Retrieval (Module 6)"])


@router.post(
    "/route",
    response_model=RetrievalRouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Route a query and retrieve chunks (vector / BM25 / graph / hybrid)",
    description=(
        "Runs Query Intelligence (Phase 7) to understand the question, then "
        "the Router picks ONE retrieval strategy:\n\n"
        "- **Fact** → Vector (FAISS semantic search)\n"
        "- **Exact policy number** (e.g. 'policy 4.2', 'POL-2024-001') → BM25\n"
        "- **Relationship** (e.g. 'how is X related to Y') → Knowledge Graph\n"
        "- **Complex / comparison** → Hybrid (BM25 + Vector + Graph, RRF-ranked)"
    ),
)
async def route_query(
    body: RetrievalRouteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
) -> RetrievalRouteResponse:
    analysis = await analyze_query(body.query, default_top_k=body.top_k)
    access_ctx = build_chunk_access_context(db, current_user, caller_role)
    result = adaptive_retrieve(db, analysis, top_k=body.top_k, access_ctx=access_ctx, document_id=body.document_id)

    return RetrievalRouteResponse(
        query=body.query,
        route=RouteDecisionOut(
            route=result.route.route,
            reason=result.route.reason,
            signals=result.route.signals,
        ),
        route_counts=result.route_counts,
        results=[
            RetrievedChunkOut(
                document_id=r["document_id"],
                chunk_index=r["chunk_index"],
                text_preview=(r["text"] or "")[:300],
                score=round(r.get("score", 0.0), 4),
                source=r.get("source", "+".join(r.get("sources", []))),
                metadata=r.get("metadata", {}),
            )
            for r in result.results
        ],
    )
