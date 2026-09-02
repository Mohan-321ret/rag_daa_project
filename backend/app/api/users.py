"""
Users API Router  –  User, Domain & Access Management
----------------------------------------------------------------------
Endpoints:
  POST  /api/v1/users/            – create an account         (USER_CREATE)
  GET   /api/v1/users/            – list accounts, filterable  (USER_READ)
  GET   /api/v1/users/{id}        – get one account             (USER_READ)
  PATCH /api/v1/users/{id}        – update profile / status / role / domains
                                     (USER_UPDATE for full_name/department,
                                      USER_DEACTIVATE for is_active,
                                      ROLE_ASSIGN for role, DOMAIN_ASSIGN for
                                      domain_ids — each field checked
                                      independently, see update_user)

"Update permissions where authorized" maps onto role assignment: this
system's permissions are entirely role-derived (see app/core/permissions.py
— there is no per-user permission override), so the only way to change what
a user can do IS to change their role. That's PATCH .../role, already gated
by ROLE_ASSIGN. "View permissions" needs no endpoint here either — the
frontend resolves a user's permissions by looking up their role against
GET /api/v1/permissions (Phase 2's introspection endpoint).

Guards enforced on every mutating endpoint, independent of the permission
checks above and independent of each other:
  - Domain scoping (assert_domain_access): a DOMAIN_MANAGER-tier caller
    (see domain_service.is_domain_unrestricted) can only see/act on users
    sharing at least one domain with them. SUPER_ADMIN/PLATFORM_OWNER are
    unrestricted. Out-of-scope targets 404, not 403 (don't confirm they exist).
  - Rank-modify guard: a caller can never modify a target whose CURRENT role
    outranks their own — independent of and in addition to can_assign_role's
    check on the role being ASSIGNED. Equal rank is allowed.
  - Self-escalation guards (Phase 1): can't change your own role, can't
    deactivate your own account.
  - can_assign_role: can't assign a role ranked above your own.

Every role/status/domain change is audit-logged (app/services/audit_service.py).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, ROLE_RANK, can_assign_role, role_has_permission
from app.db.database import get_db
from app.models.domain import Domain
from app.models.user import User
from app.models.user_domain import UserDomain
from app.schemas.auth import UserOut
from app.schemas.user import UserCreateRequest, UserListResponse, UserUpdateRequest
from app.services.auth_service import current_role, hash_password, require_permission
from app.services.audit_service import log_audit_event
from app.services.domain_service import (
    assert_domain_access,
    get_user_domain_ids,
    get_user_domains,
    is_domain_unrestricted,
    set_user_domains,
)
from app.services.user_service import build_user_out

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["User & Access Management"])


def _rank_guard(caller_role: Role, target: User) -> None:
    """Lower-level roles cannot modify higher-level administrators."""
    try:
        target_role = Role(target.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target account's role is not recognized. Contact a platform owner.",
        )
    if ROLE_RANK[target_role] > ROLE_RANK[caller_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot modify an account with a higher-ranked role than your own.",
        )


def _validate_domain_ids(db: Session, domain_ids: list[str]) -> None:
    if not domain_ids:
        return
    found = {str(d.id) for d in db.query(Domain.id).filter(Domain.id.in_(domain_ids)).all()}
    unknown = set(domain_ids) - found
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown domain id(s): {', '.join(sorted(unknown))}",
        )


def _assert_domains_in_scope(db: Session, caller: User, caller_role: Role, domain_ids: list[str]) -> None:
    """A domain-scoped caller can only grant domains it itself belongs to."""
    if is_domain_unrestricted(caller_role) or not domain_ids:
        return
    caller_domains = get_user_domain_ids(db, caller.id)
    outside = set(domain_ids) - caller_domains
    if outside:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot assign a domain you do not yourself belong to.",
        )


@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Create a user account")
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.USER_CREATE)),
    caller_role: Role = Depends(current_role),
) -> UserOut:
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    target_role = Role(body.role)
    if not can_assign_role(caller_role, target_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Cannot create an account with role '{target_role.value}': it outranks "
                f"your own role ('{caller_role.value}')."
            ),
        )

    _validate_domain_ids(db, body.domain_ids)
    _assert_domains_in_scope(db, current_user, caller_role, body.domain_ids)

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        department=body.department,
        role=target_role.value,
    )
    try:
        db.add(user)
        db.flush()
        if body.domain_ids:
            set_user_domains(db, user.id, body.domain_ids, assigned_by=current_user.id)
        log_audit_event(
            db, event_type="user_created", actor=current_user, target=user,
            after=target_role.value,
            detail=f"department={body.department!r}, domains={body.domain_ids or '(none)'}",
        )
        db.commit()
        db.refresh(user)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("[Users] Failed to create user %s: %s", email, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not create account.")

    logger.info("[Users] ➕ %s (%s) created user %s as %s", current_user.email, caller_role.value, email, target_role.value)
    return build_user_out(db, user)


@router.get("/", response_model=UserListResponse, summary="List user accounts")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.USER_READ)),
    caller_role: Role = Depends(current_role),
    q: Optional[str] = Query(default=None, description="Search by name or email"),
    role: Optional[str] = Query(default=None),
    domain_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status", description="active | inactive"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserListResponse:
    if role is not None:
        try:
            Role(role)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown role: {role}")
    if status_filter is not None and status_filter not in ("active", "inactive"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="status must be 'active' or 'inactive'")

    query = db.query(User)

    if not is_domain_unrestricted(caller_role):
        caller_domains = get_user_domain_ids(db, current_user.id)
        if not caller_domains:
            return UserListResponse(total=0, skip=skip, limit=limit, users=[])
        scoped_ids = db.query(UserDomain.user_id).filter(UserDomain.domain_id.in_(caller_domains)).subquery()
        query = query.filter(User.id.in_(scoped_ids))

    if domain_id:
        domain_user_ids = db.query(UserDomain.user_id).filter(UserDomain.domain_id == domain_id).subquery()
        query = query.filter(User.id.in_(domain_user_ids))
    if q:
        like = f"%{q}%"
        query = query.filter((User.email.ilike(like)) | (User.full_name.ilike(like)))
    if role:
        query = query.filter(User.role == role)
    if status_filter:
        query = query.filter(User.is_active.is_(status_filter == "active"))

    total = query.count()
    rows = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return UserListResponse(
        total=total, skip=skip, limit=limit,
        users=[build_user_out(db, u) for u in rows],
    )


@router.get("/{user_id}", response_model=UserOut, summary="Get one user account")
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.USER_READ)),
    caller_role: Role = Depends(current_role),
) -> UserOut:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.")
    assert_domain_access(db, current_user, caller_role, user)
    return build_user_out(db, user)


@router.patch("/{user_id}", response_model=UserOut, summary="Update a user (profile, status, role, or domains)")
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            Permission.USER_UPDATE, Permission.USER_DEACTIVATE,
            Permission.ROLE_ASSIGN, Permission.DOMAIN_ASSIGN, any_of=True,
        )
    ),
    caller_role: Role = Depends(current_role),
) -> UserOut:
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found.")

    assert_domain_access(db, current_user, caller_role, target)
    _rank_guard(caller_role, target)

    # ── Role assignment: the privilege-escalation-sensitive path ───────────────
    if body.role is not None:
        if not role_has_permission(caller_role, Permission.ROLE_ASSIGN):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This action requires permission: role:assign.")
        if str(target.id) == str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own role.")
        target_role = Role(body.role)
        if not can_assign_role(caller_role, target_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Cannot assign role '{target_role.value}': it outranks your own "
                    f"role ('{caller_role.value}'). You may only assign roles at or "
                    f"below your own level."
                ),
            )
        old_role = target.role
        target.role = target_role.value
        log_audit_event(
            db, event_type="role_changed", actor=current_user, target=target,
            before=old_role, after=target_role.value,
        )
        logger.warning(
            "[Users] 🔑 %s (%s) assigned role '%s' to %s",
            current_user.email, caller_role.value, target_role.value, target.email,
        )

    # ── Deactivation / reactivation ─────────────────────────────────────────────
    if body.is_active is not None:
        if not role_has_permission(caller_role, Permission.USER_DEACTIVATE):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This action requires permission: user:deactivate.")
        if str(target.id) == str(current_user.id) and body.is_active is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot deactivate your own account.")
        old_active = target.is_active
        target.is_active = body.is_active
        if old_active != body.is_active:
            log_audit_event(
                db, event_type="user_activated" if body.is_active else "user_deactivated",
                actor=current_user, target=target,
                before=str(old_active), after=str(body.is_active),
            )

    # ── Ordinary profile fields ─────────────────────────────────────────────────
    if body.full_name is not None or body.department is not None:
        if not role_has_permission(caller_role, Permission.USER_UPDATE):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This action requires permission: user:update.")
        if body.full_name is not None:
            target.full_name = body.full_name
        if body.department is not None:
            target.department = body.department or None

    # ── Domain membership ────────────────────────────────────────────────────────
    if body.domain_ids is not None:
        if not role_has_permission(caller_role, Permission.DOMAIN_ASSIGN):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This action requires permission: domain:assign.")
        _validate_domain_ids(db, body.domain_ids)
        _assert_domains_in_scope(db, current_user, caller_role, body.domain_ids)
        old_names = ", ".join(d.name for d in get_user_domains(db, target.id)) or "(none)"
        set_user_domains(db, target.id, body.domain_ids, assigned_by=current_user.id)
        new_names = ", ".join(
            d.name for d in db.query(Domain).filter(Domain.id.in_(body.domain_ids)).all()
        ) or "(none)"
        log_audit_event(
            db, event_type="domain_assigned", actor=current_user, target=target,
            before=old_names, after=new_names,
        )

    try:
        db.commit()
        db.refresh(target)
    except Exception as exc:
        db.rollback()
        logger.error("[Users] Failed to update user %s: %s", user_id, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not update user.")

    return build_user_out(db, target)
