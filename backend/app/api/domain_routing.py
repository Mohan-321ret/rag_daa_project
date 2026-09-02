"""
Domain Routing API Router  –  Phase 11: Domain-Based Ticket Routing
-------------------------------------------------------------------
Provides endpoints for:
- Viewing and updating domain routing configuration
- Managing domain managers and domain experts
- Manual query classification testing
- Ticket triage & manual rerouting
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.domain import Domain
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.domain_routing import (
    DomainClassifyRequest,
    DomainClassifyResponse,
    DomainManagerAssignRequest,
    DomainManagerOut,
    DomainRoutingConfigResponse,
    DomainRoutingConfigUpdateRequest,
    TicketRerouteRequest,
)
from app.schemas.ticket import TicketDetail, TicketResponse
from app.services.auth_service import get_current_user, require_permission
from app.services.domain_router_service import (
    assign_domain_manager,
    classify_domain,
    get_domain_routing_config,
    list_domain_managers_detailed,
    remove_domain_manager,
    reroute_ticket,
    update_domain_routing_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/domain-routing", tags=["Domain Routing"])


# ── Configuration Endpoints ───────────────────────────────────────────────────

@router.get(
    "/config",
    response_model=DomainRoutingConfigResponse,
    summary="Get domain routing configuration",
)
def get_routing_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DomainRoutingConfigResponse:
    """View active domain routing thresholds and parameters."""
    cfg = get_domain_routing_config(db)
    return DomainRoutingConfigResponse(**cfg)


@router.patch(
    "/config",
    response_model=DomainRoutingConfigResponse,
    summary="Update domain routing configuration (Admin only)",
)
def update_routing_config(
    body: DomainRoutingConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOMAIN_MANAGE)),
) -> DomainRoutingConfigResponse:
    """Update domain routing threshold and parameters."""
    update_data = body.model_dump(exclude_unset=True)
    cfg = update_domain_routing_config(
        db,
        update_data,
        admin_user_id=str(current_user.id) if current_user else None,
    )
    logger.info(
        "[DomainRouting] ⚙️ Configuration updated by %s",
        current_user.email,
    )
    return DomainRoutingConfigResponse(**cfg)


# ── Domain Managers Management ────────────────────────────────────────────────

@router.get(
    "/domains/{domain_id}/managers",
    response_model=List[DomainManagerOut],
    summary="List managers and experts for a domain",
)
def list_managers(
    domain_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DomainManagerOut]:
    """List all managers/experts assigned to review tickets for this domain."""
    try:
        did = uuid.UUID(domain_id) if isinstance(domain_id, str) else domain_id
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain ID format",
        )

    domain = db.query(Domain).filter(Domain.id == did).first()
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain {domain_id} not found",
        )

    rows = list_domain_managers_detailed(db, did)
    return [DomainManagerOut(**r) for r in rows]


@router.post(
    "/domains/{domain_id}/managers",
    response_model=DomainManagerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a domain manager/expert (Admin only)",
)
def assign_manager(
    domain_id: str,
    body: DomainManagerAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOMAIN_MANAGE)),
) -> DomainManagerOut:
    """Assign a user as manager/expert for this domain."""
    try:
        did = uuid.UUID(domain_id)
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for domain_id or user_id",
        )

    domain = db.query(Domain).filter(Domain.id == did).first()
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domain {domain_id} not found",
        )

    target_user = db.query(User).filter(User.id == uid).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {body.user_id} not found",
        )

    cfg = assign_domain_manager(
        db,
        domain_id=did,
        manager_user_id=uid,
        is_primary=body.is_primary_manager,
    )

    rows = list_domain_managers_detailed(db, did)
    matching = next((r for r in rows if r["manager_user_id"] == str(uid)), None)
    if matching:
        return DomainManagerOut(**matching)

    return DomainManagerOut(
        id=str(cfg.id),
        domain_id=str(domain.id),
        domain_key=domain.key,
        domain_name=domain.name,
        manager_user_id=str(target_user.id),
        manager_email=target_user.email,
        manager_name=target_user.full_name,
        manager_role=target_user.role,
        is_primary_manager=cfg.is_primary_manager,
        is_active=cfg.is_active,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


@router.delete(
    "/domains/{domain_id}/managers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a domain manager (Admin only)",
)
def remove_manager(
    domain_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOMAIN_MANAGE)),
):
    """Remove a user from being a manager for this domain."""
    try:
        did = uuid.UUID(domain_id)
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format for domain_id or user_id",
        )

    success = remove_domain_manager(db, did, uid)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manager assignment not found",
        )
    return None


# ── Domain Classification Testing Endpoint ───────────────────────────────────

@router.post(
    "/classify",
    response_model=DomainClassifyResponse,
    summary="Test domain classification for a query",
)
async def test_classify(
    body: DomainClassifyRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DomainClassifyResponse:
    """Run the 6-tier cascading domain classifier on a query."""
    result = await classify_domain(
        db,
        query_text=body.query_text,
        user_id=body.user_id,
        intent=body.intent,
        entities=body.entities,
        source_document_ids=body.source_document_ids,
        explicit_domain=body.explicit_domain,
    )

    domain_name = None
    if result.domain_id:
        dom = db.query(Domain).filter(Domain.id == result.domain_id).first()
        if dom:
            domain_name = dom.name

    return DomainClassifyResponse(
        domain_key=result.domain_key,
        domain_name=domain_name,
        domain_id=str(result.domain_id) if result.domain_id else None,
        confidence=result.confidence,
        method=result.method,
        needs_triage=result.needs_triage,
        reasoning=result.reasoning,
    )


# ── Ticket Manual Rerouting & Triage ──────────────────────────────────────────

@router.post(
    "/tickets/{ticket_id}/reroute",
    response_model=TicketDetail,
    summary="Manually reroute a ticket to a domain (Admin only)",
)
def admin_reroute_ticket(
    ticket_id: str,
    body: TicketRerouteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.TICKET_ASSIGN)),
) -> TicketDetail:
    """Admin manual resolution of a NEEDS_TRIAGE ticket or reassignment to another domain."""
    ticket = reroute_ticket(
        db,
        ticket_id=ticket_id,
        target_domain_key=body.domain_key,
        assigned_to=body.assigned_to,
        reviewer_notes=body.reviewer_notes,
        admin_user=current_user,
    )
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket '{ticket_id}' or domain '{body.domain_key}' not found",
        )
    return TicketDetail.model_validate(ticket)
