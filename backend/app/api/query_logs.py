"""
Query Logs API Router  –  Phase 9: Query Logs and Query History Management
---------------------------------------------------------------------------
Endpoints:
  GET /api/v1/query-logs/           – list query history with filtering
  GET /api/v1/query-logs/{query_id} – detailed view of a single query
  GET /api/v1/query-logs/export     – export query history

Role-based access control:
  - QUERY_LOG_VIEW_OWN: see your own queries (base right)
  - QUERY_LOG_VIEW_DOMAIN: see all queries in your domain(s)
  - QUERY_LOG_VIEW_GLOBAL: see all queries platform-wide
  - QUERY_LOG_EXPORT: export query logs (applies same own/domain/global scope)

Sensitive fields (chunk_access_violations, access_violation_details) are only
shown to users with QUERY_LOG_VIEW_DOMAIN or QUERY_LOG_VIEW_GLOBAL permission.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, role_has_any_permission
from app.db.database import get_db
from app.models.query_log import QueryLog
from app.models.user import User
from app.schemas.query_log import (
    QueryLogDetailResponse,
    QueryLogExportResponse,
    QueryLogFilterParams,
    QueryLogListItem,
    QueryLogListResponse,
)
from app.services.auth_service import current_role, require_permission
from app.services.query_log_service import (
    can_view_sensitive_fields,
    get_query_log,
    get_query_logs_scoped,
)

router = APIRouter(prefix="/query-logs", tags=["Query Management"])

_BROAD_SCOPE = (Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_VIEW_GLOBAL)


def _can_access_log(
    log: QueryLog,
    current_user: User,
    caller_role: Role,
) -> bool:
    """Check if caller can access this specific query log."""
    # Global/domain viewers can access any log
    if role_has_any_permission(caller_role, _BROAD_SCOPE):
        return True
    # Own viewer can only see own logs
    if log.user_id == current_user.id:
        return True
    return False


def _build_filters(
    intent: Optional[str] = None,
    route: Optional[str] = None,
    retrieval_strategy: Optional[str] = None,
    model_used: Optional[str] = None,
    user_role: Optional[str] = None,
    user_domain: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    ticket_status: Optional[str] = None,
    verification_result: Optional[str] = None,
    is_grounded: Optional[bool] = None,
    was_rewritten: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search_text: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """Build filter dictionary from query parameters."""
    filters = {}
    if intent:
        filters["intent"] = intent
    if route:
        filters["route"] = route
    if retrieval_strategy:
        filters["retrieval_strategy"] = retrieval_strategy
    if model_used:
        filters["model_used"] = model_used
    if user_role:
        filters["user_role"] = user_role
    if user_domain:
        filters["user_domain"] = user_domain
    if min_confidence is not None:
        filters["min_confidence"] = min_confidence
    if max_confidence is not None:
        filters["max_confidence"] = max_confidence
    if ticket_status:
        filters["ticket_status"] = ticket_status
    if verification_result:
        filters["verification_result"] = verification_result
    if is_grounded is not None:
        filters["is_grounded"] = is_grounded
    if was_rewritten is not None:
        filters["was_rewritten"] = was_rewritten
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if search_text:
        filters["search_text"] = search_text
    if user_id:
        filters["user_id"] = user_id
    return filters


@router.get("/", response_model=QueryLogListResponse, summary="List query history")
def list_query_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.QUERY_LOG_VIEW_OWN,
            Permission.QUERY_LOG_VIEW_DOMAIN,
            Permission.QUERY_LOG_VIEW_GLOBAL,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
    # Pagination
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    # Filters
    intent: Optional[str] = Query(None),
    route: Optional[str] = Query(None, description="vector|bm25|graph|hybrid"),
    retrieval_strategy: Optional[str] = Query(None),
    model_used: Optional[str] = Query(None),
    user_role: Optional[str] = Query(None),
    user_domain: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    ticket_status: Optional[str] = Query(None),
    verification_result: Optional[str] = Query(None),
    is_grounded: Optional[bool] = Query(None),
    was_rewritten: Optional[bool] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    search_text: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
) -> QueryLogListResponse:
    """List query logs with optional filtering and pagination."""
    filters = _build_filters(
        intent=intent,
        route=route,
        retrieval_strategy=retrieval_strategy,
        model_used=model_used,
        user_role=user_role,
        user_domain=user_domain,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        ticket_status=ticket_status,
        verification_result=verification_result,
        is_grounded=is_grounded,
        was_rewritten=was_rewritten,
        date_from=date_from,
        date_to=date_to,
        search_text=search_text,
        user_id=user_id,
    )
    
    logs, total, scope = get_query_logs_scoped(
        db, current_user, caller_role, skip=skip, limit=limit, filters=filters
    )
    
    return QueryLogListResponse(
        total=total,
        skip=skip,
        limit=limit,
        scope=scope,
        logs=[QueryLogListItem.model_validate(log) for log in logs],
    )


@router.get("/export", response_model=QueryLogExportResponse, summary="Export query history")
@router.get("/export/all", response_model=QueryLogExportResponse, summary="Export query history")
def export_query_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.QUERY_LOG_EXPORT)),
    caller_role: Role = Depends(current_role),
    # Filters
    intent: Optional[str] = Query(None),
    route: Optional[str] = Query(None),
    retrieval_strategy: Optional[str] = Query(None),
    model_used: Optional[str] = Query(None),
    user_role: Optional[str] = Query(None),
    user_domain: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    ticket_status: Optional[str] = Query(None),
    verification_result: Optional[str] = Query(None),
    is_grounded: Optional[bool] = Query(None),
    was_rewritten: Optional[bool] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    search_text: Optional[str] = Query(None),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> QueryLogExportResponse:
    """Export query logs as JSON (applies same access scoping as list)."""
    filters = _build_filters(
        intent=intent,
        route=route,
        retrieval_strategy=retrieval_strategy,
        model_used=model_used,
        user_role=user_role,
        user_domain=user_domain,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        ticket_status=ticket_status,
        verification_result=verification_result,
        is_grounded=is_grounded,
        was_rewritten=was_rewritten,
        date_from=date_from,
        date_to=date_to,
        search_text=search_text,
    )
    
    logs, total, _scope = get_query_logs_scoped(
        db, current_user, caller_role, skip=0, limit=limit, filters=filters
    )
    
    return QueryLogExportResponse(
        total_exported=len(logs),
        logs=[log for log in logs],  # type: ignore
    )


@router.get("/{query_id}", response_model=QueryLogDetailResponse, summary="Get query log details")
def get_query_log_detail(
    query_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.QUERY_LOG_VIEW_OWN,
            Permission.QUERY_LOG_VIEW_DOMAIN,
            Permission.QUERY_LOG_VIEW_GLOBAL,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> QueryLogDetailResponse:
    """Get detailed information about a specific query log."""
    log = get_query_log(db, query_id)
    
    if not log:
        raise HTTPException(status_code=404, detail="Query log not found")
    
    # Check access permission
    if not _can_access_log(log, current_user, caller_role):
        raise HTTPException(status_code=403, detail="Not authorized to view this query log")
    
    can_view_sensitive = can_view_sensitive_fields(caller_role, log.user_id, current_user)
    
    return QueryLogDetailResponse(
        log=log,  # type: ignore
        can_view_sensitive=can_view_sensitive,
    )
