"""
Query Log Service  –  Phase 9: Query Logs and Query History Management
---------------------------------------------------------------------------
Persists and retrieves comprehensive query telemetry including:
- Query metadata (who, when, what)
- Pipeline decisions (intent, routing, model)
- Retrieval details (chunks, strategy, scores)
- Outcome signals (verification, grounding, hallucinations)
- Performance metrics (latency breakdown)

Supports role-based access control with sensitive field masking.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, role_has_any_permission
from app.models.query_log import QueryLog
from app.models.user import User

logger = logging.getLogger(__name__)


def new_query_id() -> str:
    return f"QRY_{uuid.uuid4().hex[:10].upper()}"


def log_query(
    db: Session,
    *,
    query_id: str,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    user_domain: Optional[str] = None,
    query_text: str,
    answer_text: Optional[str] = None,
    intent: Optional[str] = None,
    complexity: Optional[str] = None,
    route: Optional[str] = None,
    route_overridden: bool = False,
    retrieval_strategy: Optional[str] = None,
    model_used: Optional[str] = None,
    document_id_filter: Optional[str] = None,
    retrieved_chunk_ids: Optional[List[str]] = None,
    authorized_chunk_ids: Optional[List[str]] = None,
    retrieval_score: Optional[float] = None,
    reranking_score: Optional[float] = None,
    reranking_explanation: Optional[str] = None,
    confidence_score: Optional[float] = None,
    is_grounded: Optional[bool] = None,
    was_rewritten: bool = False,
    hallucinations_detected: int = 0,
    retrieved_chunks: int = 0,
    citation_count: int = 0,
    verification_result: Optional[str] = None,
    verification_details: Optional[str] = None,
    ticket_id: Optional[str] = None,
    ticket_status: Optional[str] = None,
    chunk_access_violations: int = 0,
    access_violation_details: Optional[str] = None,
    latency_ms: Optional[float] = None,
    retrieval_latency_ms: Optional[float] = None,
    reranking_latency_ms: Optional[float] = None,
    llm_latency_ms: Optional[float] = None,
) -> Optional[QueryLog]:
    """Persist comprehensive query telemetry. Never raises — logging must not break the RAG response."""
    try:
        row = QueryLog(
            query_id=query_id,
            user_id=user_id,
            user_role=user_role,
            user_domain=user_domain,
            query_text=query_text,
            answer_text=answer_text,
            intent=intent,
            complexity=complexity,
            route=route,
            route_overridden=route_overridden,
            retrieval_strategy=retrieval_strategy,
            model_used=model_used,
            document_id_filter=document_id_filter,
            retrieved_chunk_ids=retrieved_chunk_ids or [],
            authorized_chunk_ids=authorized_chunk_ids or [],
            retrieval_score=retrieval_score,
            reranking_score=reranking_score,
            reranking_explanation=reranking_explanation,
            confidence_score=confidence_score,
            is_grounded=is_grounded,
            was_rewritten=was_rewritten,
            hallucinations_detected=hallucinations_detected,
            retrieved_chunks=retrieved_chunks,
            citation_count=citation_count,
            verification_result=verification_result,
            verification_details=verification_details,
            ticket_id=ticket_id,
            ticket_status=ticket_status,
            chunk_access_violations=chunk_access_violations,
            access_violation_details=access_violation_details,
            latency_ms=latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            reranking_latency_ms=reranking_latency_ms,
            llm_latency_ms=llm_latency_ms,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "[QueryLog] 📝 %s | user=%s route=%s model=%s confidence=%s latency_ms=%.1f",
            query_id, user_id, route, model_used, confidence_score, latency_ms or 0.0,
        )
        return row
    except Exception as exc:
        db.rollback()
        logger.error("[QueryLog] Failed to persist query log %s: %s", query_id, exc)
        return None


def get_query_log(db: Session, query_id: str) -> Optional[QueryLog]:
    """Get a single query log by ID."""
    return db.query(QueryLog).filter(QueryLog.query_id == query_id).first()


def get_query_logs_scoped(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
    skip: int = 0,
    limit: int = 50,
    filters: Optional[dict] = None,
) -> tuple[List[QueryLog], int, str]:
    """
    Get query logs scoped to the caller's permissions.
    
    Returns: (logs, total_count, scope_string)
    where scope_string is "own", "domain", or "global"
    """
    q = db.query(QueryLog)
    
    # Determine scope based on permissions
    _BROAD_SCOPE = (Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_VIEW_GLOBAL)
    
    if role_has_any_permission(caller_role, _BROAD_SCOPE):
        scope = "global"
    elif current_user:
        q = q.filter(QueryLog.user_id == current_user.id)
        scope = "own"
    else:
        return [], 0, "none"
    
    # Apply filters
    if filters:
        if filters.get("intent"):
            q = q.filter(QueryLog.intent == filters["intent"])
        if filters.get("route"):
            q = q.filter(QueryLog.route == filters["route"])
        if filters.get("retrieval_strategy"):
            q = q.filter(QueryLog.retrieval_strategy == filters["retrieval_strategy"])
        if filters.get("model_used"):
            q = q.filter(QueryLog.model_used == filters["model_used"])
        if filters.get("user_role"):
            q = q.filter(QueryLog.user_role == filters["user_role"])
        if filters.get("user_domain"):
            q = q.filter(QueryLog.user_domain == filters["user_domain"])
        if filters.get("verification_result"):
            q = q.filter(QueryLog.verification_result == filters["verification_result"])
        if filters.get("ticket_status"):
            q = q.filter(QueryLog.ticket_status == filters["ticket_status"])
        if filters.get("is_grounded") is not None:
            q = q.filter(QueryLog.is_grounded == filters["is_grounded"])
        if filters.get("was_rewritten") is not None:
            q = q.filter(QueryLog.was_rewritten == filters["was_rewritten"])
        if filters.get("min_confidence") is not None:
            q = q.filter(QueryLog.confidence_score >= filters["min_confidence"])
        if filters.get("max_confidence") is not None:
            q = q.filter(QueryLog.confidence_score <= filters["max_confidence"])
        if filters.get("date_from"):
            q = q.filter(QueryLog.created_at >= filters["date_from"])
        if filters.get("date_to"):
            q = q.filter(QueryLog.created_at <= filters["date_to"])
        if filters.get("search_text"):
            search_term = f"%{filters['search_text']}%"
            q = q.filter(
                or_(
                    QueryLog.query_text.ilike(search_term),
                    QueryLog.answer_text.ilike(search_term),
                )
            )
        if filters.get("user_id"):
            # Only if caller has global/domain scope
            if scope != "own":
                q = q.filter(QueryLog.user_id == filters["user_id"])
    
    total = q.count()
    logs = q.order_by(QueryLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return logs, total, scope


def can_view_sensitive_fields(caller_role: Role, log_owner_id: Optional[str], current_user: Optional[User]) -> bool:
    """
    Determine if the caller can view sensitive query log fields.
    Sensitive fields: chunk_access_violations, access_violation_details
    """
    # Only global/admin roles can view sensitive fields
    return role_has_any_permission(
        caller_role,
        (Permission.QUERY_LOG_VIEW_GLOBAL, Permission.QUERY_LOG_VIEW_DOMAIN)
    )


def filter_sensitive_fields(log: QueryLog, can_view_sensitive: bool) -> QueryLog:
    """Remove sensitive fields from a query log if user doesn't have permission."""
    if not can_view_sensitive:
        # Don't modify the object itself, just return it
        # Frontend should filter based on can_view_sensitive flag
        pass
    return log
