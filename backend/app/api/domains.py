"""
Domains API Router  –  User, Domain & Access Management
----------------------------------------------------------
Endpoints:
  GET   /api/v1/domains/          – list domains (any authenticated user —
                                      a plain name/key picklist isn't
                                      "restricted administration data")
  POST  /api/v1/domains/          – create a domain            (DOMAIN_MANAGE)
  PATCH /api/v1/domains/{id}      – rename/describe/deactivate (DOMAIN_MANAGE)

Domains are never hard-deleted (deactivate via `is_active: false` instead) —
existing UserDomain rows and any future document/domain linkage should never
dangle on a foreign key that vanished.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db.database import get_db
from app.models.domain import Domain
from app.models.user import User
from app.schemas.domain import (
    DomainCreateRequest,
    DomainListResponse,
    DomainOut,
    DomainUpdateRequest,
)
from app.services.auth_service import get_current_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/domains", tags=["Domain Management"])


@router.get("/", response_model=DomainListResponse, summary="List domains")
def list_domains(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    include_inactive: bool = False,
) -> DomainListResponse:
    q = db.query(Domain)
    if not include_inactive:
        q = q.filter(Domain.is_active.is_(True))
    rows = q.order_by(Domain.name).all()
    return DomainListResponse(total=len(rows), domains=[DomainOut.model_validate(d) for d in rows])


@router.post(
    "/", response_model=DomainOut, status_code=status.HTTP_201_CREATED, summary="Create a domain"
)
def create_domain(
    body: DomainCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOMAIN_MANAGE)),
) -> DomainOut:
    if db.query(Domain).filter(Domain.key == body.key).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A domain with key '{body.key}' already exists.",
        )
    domain = Domain(key=body.key, name=body.name, description=body.description)
    try:
        db.add(domain)
        db.commit()
        db.refresh(domain)
    except Exception as exc:
        db.rollback()
        logger.error("[Domains] Failed to create domain %s: %s", body.key, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not create domain."
        )
    logger.info("[Domains] ➕ %s created domain '%s'", current_user.email, domain.key)
    return DomainOut.model_validate(domain)


@router.patch("/{domain_id}", response_model=DomainOut, summary="Update a domain")
def update_domain(
    domain_id: str,
    body: DomainUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOMAIN_MANAGE)),
) -> DomainOut:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Domain '{domain_id}' not found.")

    if body.name is not None:
        domain.name = body.name
    if body.description is not None:
        domain.description = body.description or None
    if body.is_active is not None:
        domain.is_active = body.is_active

    try:
        db.commit()
        db.refresh(domain)
    except Exception as exc:
        db.rollback()
        logger.error("[Domains] Failed to update domain %s: %s", domain_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not update domain."
        )
    logger.info("[Domains] ✏️ %s updated domain '%s'", current_user.email, domain.key)
    return DomainOut.model_validate(domain)
