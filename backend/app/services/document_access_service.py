"""
Document Access Service  –  Domain-Aware Document Metadata
------------------------------------------------------------------
Implements the two authorization rules this phase asks for:

  1. "The domain is mandatory for enterprise documents unless the system
     explicitly supports a global/public document" — validate_visibility_domain().
  2. "Ensure unauthorized users cannot upload documents into domains they do
     not control" — assert_can_upload_to_domain(), reusing Phase 3's
     domain_service scoping helpers (a DOMAIN_MANAGER-tier uploader can only
     target a domain they themselves belong to; SUPER_ADMIN/PLATFORM_OWNER
     are unrestricted).

...plus read-side visibility scoping for the document registry
(GET /documents, GET /documents/{id}):
  - global      -> visible to anyone who can reach the endpoint at all
  - domain      -> visible to the owner/uploader, domain-unrestricted roles,
                   or anyone sharing the document's domain
  - restricted  -> visible to the owner/uploader, domain-unrestricted roles,
                   or anyone holding an explicit DocumentAccessGrant
                   (by user_id or by role)

Scope note: this governs the document REGISTRY only. It does not filter
RAG retrieval/chunk search results — that remains a later "domain-aware
retrieval" phase, exactly like the still-global-equivalent TICKET_VIEW_DOMAIN/
QUERY_LOG_VIEW_DOMAIN permissions documented in app/core/permissions.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

from app.core.permissions import Role
from app.models.document import DOCUMENT_VISIBILITIES, Document
from app.models.document_access import DocumentAccessGrant
from app.models.user import User
from app.services.domain_service import get_user_domain_ids, is_domain_unrestricted


def validate_visibility_domain(visibility: str, domain_id: Optional[str]) -> None:
    """Domain is mandatory for every visibility except 'global'."""
    if visibility not in DOCUMENT_VISIBILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"visibility must be one of {DOCUMENT_VISIBILITIES}",
        )
    if visibility != "global" and not domain_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"domain is required for visibility='{visibility}' (only 'global' documents may omit it).",
        )


def assert_can_upload_to_domain(db: Session, user: User, role: Role, domain_id: Optional[str]) -> None:
    """A domain-scoped uploader may only target a domain they themselves belong to."""
    if is_domain_unrestricted(role) or not domain_id:
        return
    if domain_id not in get_user_domain_ids(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot upload a document into a domain you do not belong to.",
        )


def _is_owner_or_uploader(user: User, document: Document) -> bool:
    uid = str(user.id)
    return uid == str(document.owner_id or "") or uid == str(document.uploaded_by_id or "")


def can_view_document(db: Session, user: User, role: Role, document: Document) -> bool:
    if document.visibility == "global":
        return True
    if is_domain_unrestricted(role) or _is_owner_or_uploader(user, document):
        return True

    if document.visibility == "domain":
        if document.domain_id is None:
            return False
        return str(document.domain_id) in get_user_domain_ids(db, user.id)

    if document.visibility == "restricted":
        grant = (
            db.query(DocumentAccessGrant)
            .filter(DocumentAccessGrant.document_id == document.document_id)
            .filter(
                (DocumentAccessGrant.user_id == user.id) | (DocumentAccessGrant.role == role.value)
            )
            .first()
        )
        return grant is not None

    return False


def assert_document_visible(db: Session, user: User, role: Role, document: Document) -> None:
    """404, not 403 — consistent with every other resource-level scope in this codebase."""
    if not can_view_document(db, user, role, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document.document_id}' not found.",
        )


def scope_document_list(query: Query, db: Session, user: User, role: Role) -> Query:
    """Filter a Document query down to what *user* is allowed to see."""
    if is_domain_unrestricted(role):
        return query

    my_domains = get_user_domain_ids(db, user.id)
    restricted_doc_ids = {
        row[0] for row in (
            db.query(DocumentAccessGrant.document_id)
            .filter((DocumentAccessGrant.user_id == user.id) | (DocumentAccessGrant.role == role.value))
            .all()
        )
    }

    conditions = [Document.visibility == "global", Document.owner_id == user.id, Document.uploaded_by_id == user.id]
    if my_domains:
        conditions.append((Document.visibility == "domain") & Document.domain_id.in_(my_domains))
    if restricted_doc_ids:
        conditions.append((Document.visibility == "restricted") & Document.document_id.in_(restricted_doc_ids))

    from sqlalchemy import or_
    return query.filter(or_(*conditions))


def grant_restricted_access(
    db: Session, document_id: str, *, user_ids: list[str] | None = None,
    roles: list[str] | None = None, granted_by=None,
) -> None:
    """Create DocumentAccessGrant rows for a newly-restricted document."""
    for uid in (user_ids or []):
        db.add(DocumentAccessGrant(document_id=document_id, user_id=uid, granted_by=granted_by))
    for role_value in (roles or []):
        db.add(DocumentAccessGrant(document_id=document_id, role=role_value, granted_by=granted_by))
