"""
Tickets API Router  –  Phase 10, 11, 12: Enterprise Ticketing System & Admin Management
-----------------------------------------------------------------------------------------
Provides endpoints for:
- Viewing and updating dynamic ticketing threshold & configuration
- Ticket listing with multi-attribute filtering (domain, status, priority, expert, date, confidence, overdue, search)
- Admin Panel Ticket Dashboard analytics & SLA metrics
- Rich ticket detail with originating QueryLog context, citations, and conversation context
- Dedicated administrative lifecycle mutations (assign, priority, status, resolve, close, notes)
- Domain-scoped RBAC enforcement (Domain Managers isolated to their authorized domains)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, role_has_any_permission
from app.db.database import get_db
from app.models.ticket import TICKET_STATUSES, Ticket, TicketPriority, TicketStatus
from app.models.user import User
from app.schemas.ticket import (
    TicketAssignActionRequest,
    TicketCloseActionRequest,
    TicketConfigResponse,
    TicketConfigUpdateRequest,
    TicketCreateRequest,
    TicketDashboardResponse,
    TicketDetail,
    TicketListItem,
    TicketListResponse,
    TicketNotesActionRequest,
    TicketPriorityActionRequest,
    TicketResolveActionRequest,
    TicketStatsResponse,
    TicketStatusActionRequest,
    TicketUpdateRequest,
)
from app.services.auth_service import current_role, get_current_user, require_permission
from app.services.ticket_service import (
    add_internal_notes as svc_add_notes,
    assign_ticket as svc_assign_ticket,
    can_user_access_ticket,
    change_ticket_priority as svc_change_priority,
    change_ticket_status as svc_change_status,
    close_ticket as svc_close_ticket,
    create_ticket_from_low_confidence,
    get_ticket,
    get_ticket_confidence_threshold,
    get_ticket_dashboard,
    get_ticket_detail_enriched,
    get_ticket_statistics,
    get_ticketing_config,
    list_tickets_scoped,
    new_ticket_id,
    resolve_ticket as svc_resolve_ticket,
    update_ticket as svc_update_ticket,
    update_ticketing_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["Enterprise Ticketing System"])


# ── Configuration Endpoints (Admin Only) ──────────────────────────────────────

@router.get(
    "/config",
    response_model=TicketConfigResponse,
    summary="Get ticketing configuration and confidence threshold",
)
def get_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_VIEW_OWN)),
    caller_role: Role = Depends(current_role),
) -> TicketConfigResponse:
    """Returns current ticketing configuration including active confidence threshold."""
    cfg = get_ticketing_config(db)
    return TicketConfigResponse(**cfg)


@router.patch(
    "/config",
    response_model=TicketConfigResponse,
    summary="Update ticketing threshold and configuration (Admin only)",
)
def update_config(
    body: TicketConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    caller_role: Role = Depends(current_role),
) -> TicketConfigResponse:
    """
    Update confidence threshold and ticketing settings.
    Requires administrator authorization (PLATFORM_OWNER, SUPER_ADMIN, or SYSTEM_CONFIG permission).
    """
    is_admin = caller_role in (Role.PLATFORM_OWNER, Role.SUPER_ADMIN) or role_has_any_permission(
        caller_role, (Permission.SYSTEM_CONFIG, Permission.PLATFORM_SETTINGS)
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configuring ticketing threshold requires administrator authorization.",
        )

    updated = update_ticketing_config(db, body, admin_user_id=current_user.id)
    logger.info(
        "[Ticket Config] ⚙️ Admin %s (%s) updated ticketing configuration: %s",
        current_user.email, caller_role.value, body.model_dump(exclude_unset=True)
    )
    return TicketConfigResponse(**updated)


# ── Ticket Creation ────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=TicketDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a support ticket manually",
)
def create_ticket_manual(
    body: TicketCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_CREATE)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Manually creates a support ticket."""
    ticket_id = new_ticket_id()
    threshold = body.confidence_threshold or get_ticket_confidence_threshold(db)

    ticket = Ticket(
        ticket_id=ticket_id,
        query_id=body.query_id,
        user_id=uuid.UUID(body.user_id) if body.user_id else current_user.id,
        title=body.title,
        description=body.description,
        original_question=body.original_question,
        generated_answer=body.generated_answer,
        confidence_score=body.confidence_score,
        confidence_threshold=threshold,
        evidence=body.evidence,
        priority=body.priority or TicketPriority.MEDIUM.value,
        domain=body.domain or "General",
        status=TicketStatus.OPEN.value,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return TicketDetail.model_validate(ticket)


# ── Ticket Listing & Dashboard Analytics ──────────────────────────────────────

@router.get(
    "/",
    response_model=TicketListResponse,
    summary="List support tickets with multi-attribute filtering and RBAC scoping",
)
def list_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_VIEW_OWN)),
    caller_role: Role = Depends(current_role),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    domain_filter: Optional[str] = Query(default=None, alias="domain"),
    department: Optional[str] = Query(default=None),
    priority_filter: Optional[str] = Query(default=None, alias="priority"),
    resolution_type: Optional[str] = Query(default=None, alias="resolution_type"),
    assigned_expert: Optional[str] = Query(default=None, alias="assigned_expert"),
    assigned_to: Optional[str] = Query(default=None, alias="assigned_to"),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    max_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    is_overdue: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> TicketListResponse:
    """
    Lists tickets with multi-attribute filtering and role-based domain scoping:
    - Standard employee/client: sees only their own tickets.
    - Domain Manager: restricted to tickets in authorized domains.
    - Super Admin / Platform Owner: unrestricted global view.
    """
    if status_filter is not None:
        normalized = status_filter.strip().lower()
        if normalized not in [s.lower() for s in TICKET_STATUSES]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status must be one of {TICKET_STATUSES}",
            )
        status_filter = normalized

    filters = {}
    if status_filter:
        filters["status"] = status_filter
    if domain_filter or department:
        filters["domain"] = domain_filter or department
    if priority_filter:
        filters["priority"] = priority_filter.lower()
    if resolution_type:
        filters["resolution_type"] = resolution_type.upper()
    if assigned_expert or assigned_to:
        filters["assigned_to"] = assigned_expert or assigned_to
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if min_confidence is not None:
        filters["min_confidence"] = min_confidence
    if max_confidence is not None:
        filters["max_confidence"] = max_confidence
    if is_overdue is not None:
        filters["is_overdue"] = is_overdue
    if search:
        filters["search_text"] = search

    tickets, total, _ = list_tickets_scoped(
        db=db,
        current_user=current_user,
        caller_role=caller_role,
        skip=skip,
        limit=limit,
        filters=filters,
    )

    return TicketListResponse(
        total=total,
        skip=skip,
        limit=limit,
        tickets=[TicketListItem.model_validate(t) for t in tickets],
    )


@router.get(
    "/dashboard",
    response_model=TicketDashboardResponse,
    summary="Admin Panel Ticket Dashboard Analytics & SLA Metrics",
)
def ticket_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_VIEW_DOMAIN,
            Permission.ANALYTICS_VIEW_PLATFORM,
            Permission.ANALYTICS_VIEW_DOMAIN,
            Permission.TICKET_VIEW_OWN,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
    domain_filter: Optional[str] = Query(default=None, alias="domain"),
) -> TicketDashboardResponse:
    """
    Returns comprehensive Admin Panel Ticket Dashboard analytics:
    total, open, unassigned, in-progress, resolved, closed, overdue tickets,
    average resolution time, and low-confidence ticket counts.
    """
    data = get_ticket_dashboard(
        db,
        current_user=current_user,
        caller_role=caller_role,
        domain_filter=domain_filter,
    )
    return TicketDashboardResponse(**data)


@router.get(
    "/stats",
    response_model=TicketStatsResponse,
    summary="Legacy Ticket queue statistics",
)
def ticket_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_VIEW_DOMAIN,
            Permission.ANALYTICS_VIEW_PLATFORM,
            Permission.ANALYTICS_VIEW_DOMAIN,
            Permission.TICKET_VIEW_OWN,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> TicketStatsResponse:
    """Returns ticket counts by status, domain, priority, and SLA metrics."""
    stats_data = get_ticket_statistics(db, current_user=current_user, caller_role=caller_role)
    return TicketStatsResponse(**stats_data)


# ── Ticket Detail ─────────────────────────────────────────────────────────────

@router.get(
    "/{ticket_id}",
    response_model=TicketDetail,
    summary="Get single enriched ticket detail",
)
def get_ticket_detail(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_VIEW_OWN)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """
    Returns complete enriched ticket details including:
    - User question, generated answer, confidence score, evidence, citations
    - Routing information & method
    - Originating QueryLog history & metrics
    - Assigned expert and resolver user details
    - SLA overdue indicators
    """
    detail = get_ticket_detail_enriched(
        db, ticket_id=ticket_id, current_user=current_user, caller_role=caller_role
    )
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )
    return detail


# ── General Ticket Update ──────────────────────────────────────────────────────

@router.patch(
    "/{ticket_id}",
    response_model=TicketDetail,
    summary="Update a ticket status, priority, assignee, or resolution",
)
def update_ticket_endpoint(
    ticket_id: str,
    body: TicketUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_ASSIGN,
            Permission.TICKET_RESOLVE,
            Permission.TICKET_CLOSE,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """General update endpoint for ticket modifications."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    # Status-specific checks
    if body.status is not None:
        if body.status == TicketStatus.RESOLVED.value:
            if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_RESOLVE})):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="TICKET_RESOLVE permission is required to resolve a ticket.",
                )
        elif body.status in (TicketStatus.CLOSED.value, TicketStatus.REJECTED.value):
            if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_CLOSE})):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="TICKET_CLOSE permission is required to close/dismiss a ticket.",
                )
        else:
            if not role_has_any_permission(
                caller_role,
                frozenset({
                    Permission.TICKET_ASSIGN,
                    Permission.TICKET_RESOLVE,
                    Permission.TICKET_CLOSE,
                }),
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="TICKET_ASSIGN permission is required to change ticket lifecycle status.",
                )

    # Assignee/priority checks
    if body.assigned_to is not None or body.priority is not None:
        if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_ASSIGN})):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TICKET_ASSIGN permission is required to update ticket assignee or priority.",
            )

    # Resolution checks
    if (
        body.resolution is not None
        or body.resolution_type is not None
        or body.supporting_evidence is not None
        or body.supporting_document_ids is not None
    ):
        if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_RESOLVE})):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TICKET_RESOLVE permission is required to resolve a ticket.",
            )

    updated = svc_update_ticket(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
        caller_role=caller_role,
        status=body.status,
        priority=body.priority,
        assigned_to=body.assigned_to,
        resolution=body.resolution,
        resolution_type=body.resolution_type,
        supporting_evidence=body.supporting_evidence,
        supporting_document_ids=body.supporting_document_ids,
        feedback=body.feedback,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update ticket {ticket_id}.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


# ── Dedicated Administrative Action Endpoints ─────────────────────────────────

@router.post(
    "/{ticket_id}/assign",
    response_model=TicketDetail,
    summary="Assign or reassign a ticket to a domain expert",
)
def assign_ticket_endpoint(
    ticket_id: str,
    body: TicketAssignActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_ASSIGN)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Assign ticket to a domain expert or unassign."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    updated = svc_assign_ticket(
        db=db,
        ticket_id=ticket_id,
        assigned_to=body.assigned_to,
        current_user=current_user,
        caller_role=caller_role,
        notes=body.notes,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to assign ticket '{ticket_id}'. Ensure target user exists and is active.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/priority",
    response_model=TicketDetail,
    summary="Change ticket priority level",
)
def priority_ticket_endpoint(
    ticket_id: str,
    body: TicketPriorityActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_ASSIGN)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Change priority (low, medium, high, critical)."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    updated = svc_change_priority(
        db=db,
        ticket_id=ticket_id,
        priority=body.priority,
        current_user=current_user,
        caller_role=caller_role,
        notes=body.notes,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to change priority for ticket '{ticket_id}'.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/status",
    response_model=TicketDetail,
    summary="Change ticket lifecycle status",
)
def status_ticket_endpoint(
    ticket_id: str,
    body: TicketStatusActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_ASSIGN,
            Permission.TICKET_RESOLVE,
            Permission.TICKET_CLOSE,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Change status (open, routed, assigned, in_progress, resolved, closed, rejected, needs_triage)."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    # Status-specific checks
    if body.status == TicketStatus.RESOLVED.value:
        if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_RESOLVE})):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TICKET_RESOLVE permission is required to resolve a ticket.",
            )
    elif body.status in (TicketStatus.CLOSED.value, TicketStatus.REJECTED.value):
        if not role_has_any_permission(caller_role, frozenset({Permission.TICKET_CLOSE})):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TICKET_CLOSE permission is required to close/dismiss a ticket.",
            )
    else:
        if not role_has_any_permission(
            caller_role,
            frozenset({
                Permission.TICKET_ASSIGN,
                Permission.TICKET_RESOLVE,
                Permission.TICKET_CLOSE,
            }),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TICKET_ASSIGN permission is required to change ticket lifecycle status.",
            )

    updated = svc_change_status(
        db=db,
        ticket_id=ticket_id,
        status_val=body.status,
        current_user=current_user,
        caller_role=caller_role,
        notes=body.notes,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update status for ticket '{ticket_id}'.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/resolve",
    response_model=TicketDetail,
    summary="Resolve a support ticket with domain expert verified answer (Phase 13)",
)
def resolve_ticket_endpoint(
    ticket_id: str,
    body: TicketResolveActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_RESOLVE)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """
    Resolve ticket with domain expert verified resolution text and root cause classification.
    Requires resolution, resolution_type, resolved_by, and resolved_at.
    """
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    updated = svc_resolve_ticket(
        db=db,
        ticket_id=ticket_id,
        resolution=body.resolution,
        current_user=current_user,
        caller_role=caller_role,
        resolution_type=body.resolution_type,
        internal_notes=body.internal_notes,
        supporting_evidence=body.supporting_evidence,
        supporting_document_ids=body.supporting_document_ids,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to resolve ticket '{ticket_id}'.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/close",
    response_model=TicketDetail,
    summary="Close a support ticket",
)
def close_ticket_endpoint(
    ticket_id: str,
    body: TicketCloseActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_CLOSE)),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Close ticket after confirmation."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    updated = svc_close_ticket(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
        caller_role=caller_role,
        feedback=body.feedback,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to close ticket '{ticket_id}'.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/notes",
    response_model=TicketDetail,
    summary="Add internal triage notes to a ticket",
)
def notes_ticket_endpoint(
    ticket_id: str,
    body: TicketNotesActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_ASSIGN,
            Permission.TICKET_RESOLVE,
            Permission.TICKET_CLOSE,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> TicketDetail:
    """Append internal reviewer/triage notes to a ticket."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or access denied.",
        )

    updated = svc_add_notes(
        db=db,
        ticket_id=ticket_id,
        notes=body.notes,
        current_user=current_user,
        caller_role=caller_role,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add internal notes to ticket '{ticket_id}'.",
        )

    detail = get_ticket_detail_enriched(db, ticket_id, current_user, caller_role)
    return detail or TicketDetail.model_validate(updated)


@router.post(
    "/{ticket_id}/create-knowledge-update",
    summary="Create a staged Knowledge Update Request from a ticket (Phase 14)",
)
def create_knowledge_update_from_ticket_endpoint(
    ticket_id: str,
    body: Optional[KnowledgeUpdateRequestCreate] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.TICKET_RESOLVE,
            Permission.TICKET_ASSIGN,
            Permission.DOCUMENT_UPLOAD,
            any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
):
    """
    Creates an administrative Knowledge Update Recommendation from a ticket.
    Production knowledge is NOT automatically modified.
    """
    from app.services.knowledge_update_service import create_request_from_ticket
    from app.schemas.knowledge_update import KnowledgeUpdateRequestOut

    req = create_request_from_ticket(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
        caller_role=caller_role,
        payload=body,
    )
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' not found or failed to create knowledge update request.",
        )
    return KnowledgeUpdateRequestOut.model_validate(req)

