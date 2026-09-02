"""
RAG API Router  –  Phase 9 & Phase 5 (Query Logging & RAG Pipeline)
-------------------------------------------------------------------
Exposes the end-to-end Retrieval-Augmented Generation pipeline with
comprehensive query logging.

Endpoints:
  POST /api/v1/rag/query          – Ask a question, get an LLM answer with sources
  GET  /api/v1/rag/status         – Check FAISS index size and RAG readiness
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.schemas import RAGCitation, RAGQueryRequest, RAGQueryResponse, RAGSource
from app.models.user import User
from app.services.auth_service import current_role, get_current_user, require_permission
from app.services.rag_service import answer_question
from app.services.vector_store import get_vector_store
from app.services.query_intelligence_service import query_analysis_to_dict
from app.services.evidence_verification_service import verification_result_to_dict
from app.services.query_log_service import log_query, new_query_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG – Phase 5"])


# ── POST /rag/query ────────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=RAGQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a question using the RAG pipeline",
    description=(
        "Embeds the question, retrieves the top-k most relevant document chunks "
        "from FAISS, builds a context-enriched prompt, and returns an LLM-generated "
        "answer with source citations.\n\n"
        "**Pipeline:** Question → Query Intelligence → Adaptive Router "
        "(Vector/BM25/Graph/Hybrid) → Context Fusion (dedup/rerank/compress) "
        "→ Enterprise LLM (Llama 3/Gemma/Mistral/Qwen) → Evidence Verification "
        "(re-check claims, confidence score, hallucination correction) → "
        "Verified Answer + Citations\n\n"
        "The response's `query_id` can be submitted to "
        "`POST /api/v1/feedback/submit` (👍/👎 + optional correction) so "
        "Phase 12's Continuous Learning loop can track performance and "
        "improve future routing/retrieval decisions."
    ),
)
async def rag_query(
    body: RAGQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
) -> RAGQueryResponse:
    """
    Full RAG pipeline endpoint.

    - Validates question is non-empty.
    - Routes retrieval adaptively (Phase 8) over ingested document chunks.
    - Sends retrieved context + question to the configured LLM.
    - Returns the answer with source chunk citations.
    - Logs comprehensive query telemetry for Phase 9.
    """
    query_id = new_query_id()
    start_time = time.time()
    
    logger.info(
        "[RAG API] Question received | query_id=%s q='%s...' top_k=%d doc=%s",
        query_id, body.question[:60], body.top_k, body.document_id,
    )

    try:
        result = await answer_question(
            db=db,
            query=body.question,
            current_user=current_user,
            caller_role=caller_role,
            top_k=body.top_k,
            document_id=body.document_id,
            score_threshold=body.score_threshold,
            model=body.model,
        )
    except RuntimeError as exc:
        logger.error("[RAG API] Pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RAG pipeline error: {exc}",
        )
    except Exception as exc:
        logger.error("[RAG API] Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected RAG error: {exc}",
        )

    sources = [RAGSource(**s) for s in result["sources"]]

    logger.info(
        "[RAG API] ✅ Response ready | query_id=%s chunks=%d docs_cited=%d",
        query_id,
        result["retrieved_chunks"],
        len({s.document_id for s in sources}),
    )

    # Extract Phase 9 query logging information
    query_analysis = result.get("query_analysis")
    route = result.get("retrieval_route")
    grounding = result.get("grounding")
    verification = result.get("verification")
    latency_ms = time.time() - start_time

    # Extract intent and complexity from query analysis
    intent = None
    complexity = None
    if query_analysis:
        if hasattr(query_analysis, 'intent') and query_analysis.intent:
            intent_obj = query_analysis.intent
            if hasattr(intent_obj, 'intent'):
                intent = intent_obj.intent
            else:
                intent = str(intent_obj)[:32]
        if hasattr(query_analysis, 'complexity') and query_analysis.complexity:
            comp_obj = query_analysis.complexity
            if hasattr(comp_obj, 'level'):
                complexity = comp_obj.level
            else:
                complexity = str(comp_obj)[:32]

    # Extract route information
    route_str = None
    if route:
        route_str = route.route if hasattr(route, 'route') else str(route)

    # Extract confidence and grounding info
    confidence_score = None
    is_grounded = False
    if verification:
        confidence_score = verification.confidence_score if hasattr(verification, 'confidence_score') else None
    if grounding:
        is_grounded = grounding.is_grounded if hasattr(grounding, 'is_grounded') else False

    # Extract verification result
    verification_result = None
    verification_details = None
    if verification:
        if hasattr(verification, 'status'):
            verification_result = verification.status
        if hasattr(verification, 'corrections') and verification.corrections:
            verification_result = 'partial'
        if hasattr(verification, 'hallucinations_detected') and verification.hallucinations_detected:
            verification_result = 'failed'
        else:
            verification_result = 'verified'

    # Get ticket information if created
    ticket_info = result.get("ticket")
    ticket_id = None
    ticket_status = None
    if ticket_info:
        ticket_id = ticket_info.get("id")
        ticket_status = ticket_info.get("status")

    # Extract retrieved chunk information
    retrieved_chunk_ids = []
    authorized_chunk_ids = []
    if result.get("sources"):
        for source in result["sources"]:
            if isinstance(source, dict):
                chunk_id = source.get("chunk_id") or f"{source.get('document_id')}_{source.get('chunk_index')}"
                retrieved_chunk_ids.append(chunk_id)
                authorized_chunk_ids.append(chunk_id)  # All retrieved chunks are authorized
            else:
                chunk_id = f"{source.document_id}_{source.chunk_index}" if hasattr(source, 'chunk_index') else str(source.document_id)
                retrieved_chunk_ids.append(chunk_id)
                authorized_chunk_ids.append(chunk_id)

    # Log the query
    _ = log_query(
        db=db,
        query_id=query_id,
        user_id=str(current_user.id) if current_user else None,
        user_role=caller_role.value if caller_role else None,
        user_domain=current_user.department if current_user else None,
        query_text=body.question,
        answer_text=result.get("answer"),
        intent=intent,
        complexity=complexity,
        route=route_str,
        route_overridden=result.get("route_overridden", False),
        retrieval_strategy=route_str,
        model_used=result.get("model_used"),
        document_id_filter=body.document_id,
        retrieved_chunk_ids=retrieved_chunk_ids,
        authorized_chunk_ids=authorized_chunk_ids,
        retrieval_score=result.get("retrieval_score"),
        reranking_score=result.get("reranking_score"),
        reranking_explanation=result.get("reranking_explanation"),
        confidence_score=confidence_score,
        is_grounded=is_grounded,
        was_rewritten=result.get("was_rewritten", False),
        hallucinations_detected=result.get("hallucinations_detected", 0),
        retrieved_chunks=result.get("retrieved_chunks", 0),
        citation_count=len(grounding.citations) if grounding and hasattr(grounding, 'citations') else 0,
        verification_result=verification_result,
        verification_details=verification_details,
        ticket_id=ticket_id,
        ticket_status=ticket_status,
        chunk_access_violations=result.get("chunk_access_violations", 0),
        access_violation_details=result.get("access_violation_details"),
        latency_ms=latency_ms * 1000,  # Convert to milliseconds
        retrieval_latency_ms=result.get("retrieval_latency_ms"),
        reranking_latency_ms=result.get("reranking_latency_ms"),
        llm_latency_ms=result.get("llm_latency_ms"),
    )

    return RAGQueryResponse(
        query=result["query"],
        query_id=query_id,
        answer=result["answer"],
        sources=sources,
        retrieved_chunks=result["retrieved_chunks"],
        total_indexed=result["total_indexed"],
        provider=result.get("provider") or settings.llm_provider,
        query_analysis=query_analysis_to_dict(query_analysis) if query_analysis else None,
        retrieval_route=(
            {"route": route.route, "reason": route.reason, "signals": route.signals}
            if route else None
        ),
        context_fusion=result.get("context_fusion"),
        model_used=result.get("model_used"),
        is_grounded=grounding.is_grounded if grounding else None,
        citations=(
            [
                RAGCitation(
                    document_id=c.document_id,
                    chunk_index=c.chunk_index,
                    text_preview=c.text_preview,
                    source=c.source,
                )
                for c in grounding.citations
            ]
            if grounding else []
        ),
        verification=verification_result_to_dict(verification) if verification else None,
        ticket=result.get("ticket"),
        latency_ms=latency_ms * 1000,
    )


# ── GET /rag/status ────────────────────────────────────────────────────────────

@router.get(
    "/status",
    summary="RAG system readiness check",
    description="Returns the current FAISS index size and configured LLM provider.",
    tags=["RAG – Phase 5"],
)
def rag_status(_: User = Depends(get_current_user)):
    """
    Quick health-check for the RAG subsystem.
    Reports whether the knowledge base has any indexed chunks.
    """
    store = get_vector_store()
    total = store.total

    return {
        "status": "ready" if total > 0 else "empty",
        "total_indexed_chunks": total,
        "llm_provider": settings.llm_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "message": (
            f"RAG pipeline ready. {total} chunks indexed."
            if total > 0
            else "No documents indexed yet. Upload documents first via POST /api/v1/documents/upload"
        ),
    }
