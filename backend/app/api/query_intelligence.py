"""
Query Intelligence API Router  –  Phase 7 Module 5
------------------------------------------------------
Endpoint: POST /api/v1/query/analyze

Standalone access to the Query Intelligence pipeline (parser → intent →
NER → complexity → temporal) for inspection/testing. The same pipeline
runs automatically inside POST /api/v1/rag/query (Phase 5 RAG endpoint)
to adapt retrieval breadth to query complexity.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status

from app.core.permissions import Permission
from app.models.user import User
from app.schemas.query_intelligence import QueryAnalysisResponse, QueryAnalyzeRequest
from app.services.auth_service import require_permission
from app.services.query_intelligence_service import analyze_query, query_analysis_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["Query Intelligence (Module 5)"])


@router.post(
    "/analyze",
    response_model=QueryAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a query: intent, entities, complexity, temporal scope",
    description=(
        "Runs the full Query Intelligence pipeline on a raw question:\n\n"
        "**Query Parser → Intent Detection → NER → Complexity Analyzer → "
        "Temporal Detection**"
    ),
)
async def analyze(
    body: QueryAnalyzeRequest,
    _: User = Depends(require_permission(Permission.DOCUMENT_READ)),
) -> QueryAnalysisResponse:
    analysis = await analyze_query(body.query, default_top_k=body.top_k)
    return QueryAnalysisResponse(**query_analysis_to_dict(analysis))
