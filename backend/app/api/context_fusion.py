"""
Context Fusion API Router  –  Phase 9 Module 7
------------------------------------------------------
Endpoint: POST /api/v1/context/fuse

Standalone access to Query Intelligence → Adaptive Retrieval → Context
Fusion (dedup → cross-encoder rerank → compression → prompt builder) for
inspection/testing, WITHOUT calling the LLM. The same pipeline runs
automatically inside POST /api/v1/rag/query to build the final prompt.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.user import User
from app.schemas.context_fusion import (
    ContextFuseRequest,
    ContextFuseResponse,
    ContextFusionStatsOut,
    FusedChunkOut,
)
from app.services.adaptive_retrieval_service import adaptive_retrieve
from app.services.auth_service import current_role, require_permission
from app.services.chunk_access_service import build_chunk_access_context
from app.services.context_fusion_service import fuse_context
from app.services.query_intelligence_service import analyze_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context", tags=["Context Fusion (Module 7)"])


@router.post(
    "/fuse",
    response_model=ContextFuseResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve and fuse context for a query (dedup + rerank + compress)",
    description=(
        "Runs Query Intelligence (Phase 7) + Adaptive Retrieval (Phase 8), then "
        "Context Fusion (Phase 9):\n\n"
        "**Duplicate Removal → Cross Encoder Ranking → Context Compression → "
        "Prompt Builder → Optimized Context**\n\n"
        "Does not call the LLM — use this to inspect exactly what context the "
        "RAG pipeline would send it."
    ),
)
async def fuse(
    body: ContextFuseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
) -> ContextFuseResponse:
    analysis = await analyze_query(body.query, default_top_k=body.top_k)
    access_ctx = build_chunk_access_context(db, current_user, caller_role)
    retrieval = adaptive_retrieve(
        db, analysis, top_k=analysis.suggested_top_k, access_ctx=access_ctx, document_id=body.document_id
    )
    fusion = fuse_context(analysis.normalized_query, retrieval.results)

    return ContextFuseResponse(
        query=body.query,
        retrieval_route={
            "route": retrieval.route.route,
            "reason": retrieval.route.reason,
            "signals": retrieval.route.signals,
        },
        stats=ContextFusionStatsOut(**fusion.stats),
        optimized_context=fusion.prompt.optimized_context,
        chunks=[
            FusedChunkOut(
                document_id=r.get("document_id") or r.get("metadata", {}).get("document_id", "unknown"),
                chunk_index=r.get("chunk_index", r.get("metadata", {}).get("chunk_index", -1)),
                text=r.get("text", ""),
                score=round(r.get("score", 0.0), 4),
                source=r.get("source", "+".join(r.get("sources", []))),
                original_char_count=r.get("original_char_count"),
                compressed_char_count=r.get("compressed_char_count"),
            )
            for r in fusion.results
        ],
    )
