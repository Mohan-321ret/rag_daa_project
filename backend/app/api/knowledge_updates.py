"""
Knowledge Updates API Router — Phase 14: Ticket-Driven Knowledge Evolution
--------------------------------------------------------------------------
Endpoints:
  GET  /knowledge-updates/                 – List knowledge update recommendations
  GET  /knowledge-updates/stats            – Queue statistics and metrics
  GET  /knowledge-updates/{request_id}     – Full detail of an update recommendation
  POST /knowledge-updates/{request_id}/review – Admin approve/reject/cancel
  POST /knowledge-updates/{request_id}/apply  – Admin apply update (Evolution pipeline)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.user import User
from app.schemas.knowledge_update import (
    KnowledgeUpdateRequestApply,
    KnowledgeUpdateRequestCreate,
    KnowledgeUpdateRequestListResponse,
    KnowledgeUpdateRequestOut,
    KnowledgeUpdateRequestReview,
    KnowledgeUpdateStatsResponse,
)
from app.services.auth_service import current_role, get_current_user, require_permission
from app.services.knowledge_update_service import (
    apply_knowledge_update,
    get_knowledge_update_stats,
    get_update_request,
    list_update_requests,
    review_update_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-updates", tags=["Knowledge Updates (Phase 14)"])


@router.get(
    "/",
    response_model=KnowledgeUpdateRequestListResponse,
    summary="List knowledge update recommendations with role-based domain scoping",
)
def list_knowledge_updates_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_MONITOR, Permission.TICKET_VIEW_OWN, any_of=True)),
    caller_role: Role = Depends(current_role),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    domain_filter: Optional[str] = Query(default=None, alias="domain"),
    root_cause_filter: Optional[str] = Query(default=None, alias="root_cause"),
    ticket_id: Optional[str] = Query(default=None),
    document_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> KnowledgeUpdateRequestListResponse:
    """List update requests."""
    filters = {}
    if status_filter:
        filters["status"] = status_filter
    if domain_filter:
        filters["domain"] = domain_filter
    if root_cause_filter:
        filters["root_cause"] = root_cause_filter
    if ticket_id:
        filters["ticket_id"] = ticket_id
    if document_id:
        filters["document_id"] = document_id
    if search:
        filters["search"] = search

    items, total = list_update_requests(
        db=db,
        current_user=current_user,
        caller_role=caller_role,
        filters=filters,
        skip=skip,
        limit=limit,
    )
    return KnowledgeUpdateRequestListResponse(
        total=total,
        skip=skip,
        limit=limit,
        requests=[KnowledgeUpdateRequestOut.model_validate(req) for req in items],
    )


@router.get(
    "/stats",
    response_model=KnowledgeUpdateStatsResponse,
    summary="Summary statistics for knowledge update recommendations",
)
def get_knowledge_updates_stats_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_MONITOR, Permission.TICKET_VIEW_OWN, any_of=True)),
    caller_role: Role = Depends(current_role),
) -> KnowledgeUpdateStatsResponse:
    """Get dashboard stats."""
    data = get_knowledge_update_stats(db, current_user, caller_role)
    return KnowledgeUpdateStatsResponse(**data)


@router.get(
    "/{request_id}",
    response_model=KnowledgeUpdateRequestOut,
    summary="Get detail of a knowledge update recommendation",
)
def get_knowledge_update_detail_endpoint(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    caller_role: Role = Depends(current_role),
) -> KnowledgeUpdateRequestOut:
    """Get single knowledge update request detail."""
    req = get_update_request(db, request_id, current_user, caller_role)
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge update request '{request_id}' not found or access denied.",
        )
    return KnowledgeUpdateRequestOut.model_validate(req)


@router.post(
    "/{request_id}/review",
    response_model=KnowledgeUpdateRequestOut,
    summary="Administrator review action: approve or reject recommendation",
)
def review_knowledge_update_endpoint(
    request_id: str,
    body: KnowledgeUpdateRequestReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.DOCUMENT_VERSION_MANAGE,
            Permission.DOMAIN_MANAGE,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> KnowledgeUpdateRequestOut:
    """Approve or reject a knowledge update proposal."""
    req = review_update_request(
        db=db,
        request_id=request_id,
        action=body.action,
        admin_notes=body.admin_notes,
        current_user=current_user,
        caller_role=caller_role,
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge update request '{request_id}' not found or access denied.",
        )
    return KnowledgeUpdateRequestOut.model_validate(req)


@router.post(
    "/{request_id}/apply",
    summary="Administrator applies approved update: runs Evolution pipeline, diff, drift, and reindex",
)
def apply_knowledge_update_endpoint(
    request_id: str,
    body: KnowledgeUpdateRequestApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.DOCUMENT_VERSION_MANAGE,
            Permission.DOMAIN_MANAGE,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
):
    """
    Executes the approved update through Knowledge Evolution Engine.
    Diffs old vs new text, computes drift, checks conflicts, and incrementally reindexes.
    """
    result = apply_knowledge_update(
        db=db,
        request_id=request_id,
        updated_text=body.updated_text,
        target_filename=body.target_filename,
        language_hint=body.language_hint,
        admin_notes=body.admin_notes,
        current_user=current_user,
        caller_role=caller_role,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to apply knowledge update for '{request_id}'. Ensure request is approved.",
        )
    return result
