"""
Domain Service  –  User, Domain & Access Management
--------------------------------------------------------
Domain membership (User <-> Domain, many-to-many via UserDomain) and the
scoping rules that make "Domain Manager can manage users only within their
assigned domain(s)" real rather than aspirational.

Only SUPER_ADMIN and PLATFORM_OWNER are domain-UNRESTRICTED ("Platform Owner
can manage all users. Super Admin can manage users according to the
permission matrix" — no domain boundary for either). Every other role that
holds a user-management permission (in practice, only DOMAIN_MANAGER does —
see app/core/permissions.py) is scoped to users it shares a domain with.
Rank-based, not name-based, so this keeps working correctly if the matrix
ever grants user-management permissions to another sub-SUPER_ADMIN role.
"""
from __future__ import annotations

from typing import List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_RANK, Role
from app.models.domain import Domain
from app.models.user import User
from app.models.user_domain import UserDomain


def is_domain_unrestricted(role: Role) -> bool:
    """SUPER_ADMIN and PLATFORM_OWNER manage users platform-wide, no domain boundary."""
    return ROLE_RANK[role] >= ROLE_RANK[Role.SUPER_ADMIN]


def get_user_domain_ids(db: Session, user_id) -> Set[str]:
    rows = db.query(UserDomain.domain_id).filter(UserDomain.user_id == user_id).all()
    return {str(r[0]) for r in rows}


def get_user_domains(db: Session, user_id) -> List[Domain]:
    return (
        db.query(Domain)
        .join(UserDomain, UserDomain.domain_id == Domain.id)
        .filter(UserDomain.user_id == user_id)
        .order_by(UserDomain.is_primary.desc(), Domain.name)
        .all()
    )


def get_primary_domain(db: Session, user_id) -> Optional[Domain]:
    row = (
        db.query(Domain)
        .join(UserDomain, UserDomain.domain_id == Domain.id)
        .filter(UserDomain.user_id == user_id, UserDomain.is_primary.is_(True))
        .first()
    )
    return row


def shares_domain(db: Session, user_a_id, user_b_id) -> bool:
    a = get_user_domain_ids(db, user_a_id)
    if not a:
        return False  # a caller with zero domains manages nobody — fail closed
    b = get_user_domain_ids(db, user_b_id)
    return bool(a & b)


def assert_domain_access(db: Session, caller: User, caller_role: Role, target: User) -> None:
    """
    Raise 404 (not 403 — consistent with tickets/query-logs: don't confirm a
    user exists to someone who can't see them) if *caller* is domain-scoped
    and doesn't share a domain with *target*.
    """
    if is_domain_unrestricted(caller_role):
        return
    if str(caller.id) == str(target.id):
        return  # never block a caller from their own record
    if not shares_domain(db, caller.id, target.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{target.id}' not found.",
        )


def set_user_domains(db: Session, user_id, domain_ids: List[str], assigned_by=None) -> None:
    """Replace *user_id*'s domain membership with exactly *domain_ids* (first = primary)."""
    db.query(UserDomain).filter(UserDomain.user_id == user_id).delete(synchronize_session=False)
    for i, domain_id in enumerate(domain_ids):
        db.add(UserDomain(
            user_id=user_id, domain_id=domain_id,
            is_primary=(i == 0), assigned_by=assigned_by,
        ))
