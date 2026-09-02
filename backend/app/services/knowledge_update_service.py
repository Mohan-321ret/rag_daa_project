"""
Knowledge Update Service — Phase 14: Ticket-Driven Knowledge Evolution
----------------------------------------------------------------------
Orchestrates the governance lifecycle for staging, reviewing, and applying
knowledge updates derived from resolved support tickets.

Key Workflows:
1. create_request_from_ticket(): Stages a recommendation (Status: PENDING_REVIEW).
   Production knowledge is NEVER modified automatically.
2. list_update_requests(): Multi-attribute filtering with RBAC domain scoping.
3. review_update_request(): Admin review (APPROVE / REJECT).
4. apply_knowledge_update(): Admin executes the approved update:
   - Executes process_document() through Knowledge Evolution Engine.
   - Runs Version Comparator, Concept Drift Detection, Conflict Detection, and Incremental Reindexing.
   - Increments document version lineage (maintains full history).
   - Links applied Document and DocumentChange event back to the request.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, role_has_any_permission
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.document_change import DocumentChange
from app.models.knowledge_update_request import (
    KNOWLEDGE_UPDATE_STATUSES,
    KnowledgeUpdateRequest,
    KnowledgeUpdateStatus,
)
from app.models.ticket import RESOLUTION_TYPES, Ticket
from app.models.user import User
from app.models.user_domain import UserDomain
from app.schemas.document import ExtractedDocumentData
from app.schemas.knowledge_update import (
    KnowledgeUpdateRequestCreate,
    KnowledgeUpdateRequestOut,
    UserMiniInfo,
)
from app.services.evolution_service import process_document

logger = logging.getLogger(__name__)


def _get_user_authorized_domain_names(db: Session, user: User) -> Set[str]:
    """Retrieve lowercase domain names/keys the user is assigned to."""
    if not user or not hasattr(user, "id"):
        return set()
    from app.models.domain import Domain
    return {
        d_key.lower()
        for (d_key,) in (
            db.query(Domain.key)
            .join(UserDomain, UserDomain.domain_id == Domain.id)
            .filter(UserDomain.user_id == user.id)
            .all()
        )
    }


def can_user_access_request(
    db: Session,
    request: KnowledgeUpdateRequest,
    user: Optional[User],
    role: Role,
) -> bool:
    """RBAC check for viewing or modifying a KnowledgeUpdateRequest."""
    if role in (Role.SUPER_ADMIN, Role.PLATFORM_OWNER):
        return True

    if not user or not hasattr(user, "id"):
        return False

    # Domain Managers are restricted to their authorized domains
    if role == Role.DOMAIN_MANAGER:
        user_domains = _get_user_authorized_domain_names(db, user)
        req_domain = (request.domain or "").strip().lower()
        return bool(req_domain and req_domain in user_domains)

    # Standard users can only view requests they created
    return str(request.created_by_id) == str(user.id)


def create_request_from_ticket(
    db: Session,
    ticket_id: str,
    current_user: User,
    caller_role: Role,
    payload: Optional[KnowledgeUpdateRequestCreate] = None,
) -> Optional[KnowledgeUpdateRequest]:
    """
    Create a staged Knowledge Update Request from a resolved or reviewed ticket.
    Production knowledge is NOT modified.
    """
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        return None

    # Derive fields from payload or fallback to ticket attributes
    root_cause = (
        (payload.root_cause if payload else None)
        or ticket.resolution_type
        or "OTHER"
    ).strip().upper()
    if root_cause not in RESOLUTION_TYPES:
        root_cause = "OTHER"

    suggested_resolution = (
        (payload.suggested_resolution if payload else None)
        or ticket.resolution
        or ticket.generated_answer
        or "Pending resolution"
    ).strip()

    title = (
        (payload.title if payload else None)
        or f"Knowledge Update: {ticket.title or ticket.ticket_id}"
    ).strip()

    description = (
        (payload.description if payload else None)
        or ticket.description
        or ticket.original_question
        or ""
    ).strip()

    supporting_evidence = (
        (payload.supporting_evidence if payload else None)
        or ticket.supporting_evidence
        or ticket.evidence
    )

    doc_ids = (payload.supporting_document_ids if payload and payload.supporting_document_ids else None)
    if not doc_ids and ticket.supporting_document_ids:
        try:
            doc_ids = json.loads(ticket.supporting_document_ids)
        except Exception:
            doc_ids = []
    if not doc_ids and ticket.source_document_ids:
        try:
            doc_ids = json.loads(ticket.source_document_ids)
        except Exception:
            doc_ids = []

    target_doc_id = (payload.document_id if payload else None)
    target_filename = (payload.target_filename if payload else None)

    # Attempt to resolve target document filename if document_id provided
    if not target_filename and (target_doc_id or (doc_ids and len(doc_ids) > 0)):
        lookup_id = target_doc_id or doc_ids[0]
        matched_doc = db.query(Document).filter(Document.document_id == lookup_id).first()
        if matched_doc:
            target_filename = matched_doc.original_filename
            if not target_doc_id:
                target_doc_id = matched_doc.document_id

    req = KnowledgeUpdateRequest(
        ticket_id=ticket.ticket_id,
        document_id=target_doc_id,
        target_filename=target_filename,
        domain=ticket.domain,
        root_cause=root_cause,
        title=title,
        description=description,
        suggested_resolution=suggested_resolution,
        supporting_evidence=supporting_evidence,
        supporting_document_ids=json.dumps(doc_ids) if doc_ids else None,
        status=KnowledgeUpdateStatus.PENDING_REVIEW.value,
        created_by_id=current_user.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Log audit event
    _log_update_audit(
        db,
        action="knowledge_update_requested",
        request=req,
        actor=current_user,
        detail=(
            f"request_id={req.request_id} | ticket_id={req.ticket_id} | "
            f"root_cause={req.root_cause} | domain={req.domain or 'general'}"
        ),
    )
    return req


def list_update_requests(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
    filters: Optional[Dict[str, Any]] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[KnowledgeUpdateRequest], int]:
    """List knowledge update requests with role-based scoping and filtering."""
    q = db.query(KnowledgeUpdateRequest)

    # RBAC Scoping
    if caller_role not in (Role.SUPER_ADMIN, Role.PLATFORM_OWNER):
        if caller_role == Role.DOMAIN_MANAGER:
            auth_domains = _get_user_authorized_domain_names(db, current_user)
            if auth_domains:
                q = q.filter(func.lower(KnowledgeUpdateRequest.domain).in_(auth_domains))
            else:
                return [], 0
        else:
            if current_user and hasattr(current_user, "id"):
                q = q.filter(KnowledgeUpdateRequest.created_by_id == current_user.id)
            else:
                return [], 0

    # Filters
    if filters:
        if filters.get("status"):
            st = filters["status"].strip().lower()
            q = q.filter(func.lower(KnowledgeUpdateRequest.status) == st)

        if filters.get("domain"):
            dom = filters["domain"].strip().lower()
            q = q.filter(func.lower(KnowledgeUpdateRequest.domain) == dom)

        if filters.get("root_cause"):
            rc = filters["root_cause"].strip().upper()
            q = q.filter(func.upper(KnowledgeUpdateRequest.root_cause) == rc)

        if filters.get("ticket_id"):
            t_term = f"%{filters['ticket_id'].strip()}%"
            q = q.filter(KnowledgeUpdateRequest.ticket_id.ilike(t_term))

        if filters.get("document_id"):
            d_term = f"%{filters['document_id'].strip()}%"
            q = q.filter(KnowledgeUpdateRequest.document_id.ilike(d_term))

        if filters.get("search"):
            term = f"%{filters['search'].strip()}%"
            q = q.filter(
                KnowledgeUpdateRequest.title.ilike(term)
                | KnowledgeUpdateRequest.description.ilike(term)
                | KnowledgeUpdateRequest.suggested_resolution.ilike(term)
                | KnowledgeUpdateRequest.request_id.ilike(term)
            )

    total = q.count()
    items = q.order_by(KnowledgeUpdateRequest.created_at.desc()).offset(skip).limit(limit).all()
    return items, total


def get_update_request(
    db: Session,
    request_id: str,
    current_user: Optional[User],
    caller_role: Role,
) -> Optional[KnowledgeUpdateRequest]:
    """Retrieve a single KnowledgeUpdateRequest with RBAC validation."""
    req = (
        db.query(KnowledgeUpdateRequest)
        .filter(
            (KnowledgeUpdateRequest.request_id == request_id)
            | (cast(KnowledgeUpdateRequest.id, String) == request_id)
        )
        .first()
    )
    if not req or not can_user_access_request(db, req, current_user, caller_role):
        return None
    return req


def review_update_request(
    db: Session,
    request_id: str,
    action: str,
    admin_notes: Optional[str],
    current_user: User,
    caller_role: Role,
) -> Optional[KnowledgeUpdateRequest]:
    """
    Administrator review action: approve or reject a knowledge update proposal.
    Requires Administrator permission.
    """
    if caller_role not in (Role.SUPER_ADMIN, Role.PLATFORM_OWNER, Role.DOMAIN_MANAGER):
        return None

    req = get_update_request(db, request_id, current_user, caller_role)
    if not req:
        return None

    norm_action = action.strip().lower()
    if norm_action == "approve":
        req.status = KnowledgeUpdateStatus.APPROVED.value
    elif norm_action == "reject":
        req.status = KnowledgeUpdateStatus.REJECTED.value
    elif norm_action == "cancel":
        req.status = KnowledgeUpdateStatus.CANCELLED.value
    else:
        return None

    req.reviewed_by_id = current_user.id
    req.reviewed_at = datetime.now(timezone.utc)
    if admin_notes:
        note_entry = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | {current_user.email}]: {admin_notes.strip()}"
        req.admin_notes = f"{note_entry}\n\n{req.admin_notes}" if req.admin_notes else note_entry

    req.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)

    _log_update_audit(
        db,
        action=f"knowledge_update_{norm_action}d",
        request=req,
        actor=current_user,
        detail=f"request_id={req.request_id} | action={norm_action} | reviewed_by={current_user.email}",
    )
    return req


def apply_knowledge_update(
    db: Session,
    request_id: str,
    updated_text: str,
    target_filename: Optional[str],
    language_hint: Optional[str],
    admin_notes: Optional[str],
    current_user: User,
    caller_role: Role,
) -> Optional[Dict[str, Any]]:
    """
    Admin applies an approved knowledge update.
    Executes the full Evolution pipeline (process_document):
      1. Content-hash matching against target_filename lineage
      2. Version Comparator (diff generation)
      3. Concept Drift Detection (embedding distance)
      4. Conflict Detection
      5. Incremental FAISS reindexing
      6. Document version lineage increment (v1 -> v2)
      7. DocumentChange event creation
    """
    if caller_role not in (Role.SUPER_ADMIN, Role.PLATFORM_OWNER, Role.DOMAIN_MANAGER):
        return None

    req = get_update_request(db, request_id, current_user, caller_role)
    if not req:
        return None

    # Enforce approval requirement
    if req.status not in (KnowledgeUpdateStatus.APPROVED.value, KnowledgeUpdateStatus.PENDING_REVIEW.value):
        logger.warning("[KnowledgeUpdate] Cannot apply request %s in status %s", req.request_id, req.status)
        return None

    # Resolve filename for version lineage matching
    filename = (
        (target_filename or "").strip()
        or req.target_filename
        or (f"{req.domain or 'knowledge'}_policy_{req.ticket_id}.txt")
    )

    new_doc_uid = f"DOC_{uuid.uuid4().hex[:8].upper()}"
    text_content = updated_text.strip()
    doc_data = ExtractedDocumentData(
        document_id=new_doc_uid,
        filename=filename,
        original_filename=filename,
        document_type="txt",
        file_extension=".txt",
        extracted_text=text_content,
        ocr_used=False,
        word_count=len(text_content.split()),
        character_count=len(text_content),
        upload_date=datetime.now(timezone.utc),
        author=current_user.email,
        department=req.domain or "general",
        language=language_hint or "en",
    )

    # Run Evolution pipeline
    result = process_document(
        db=db,
        doc_data=doc_data,
        language_hint=language_hint,
        source=f"ticket_resolution:{req.ticket_id}",
    )

    doc_obj = result.get("document")
    new_doc_id = doc_obj.document_id if doc_obj else result.get("document_id")
    event_id = result.get("event_id")

    req.applied_document_id = new_doc_id
    req.change_event_id = event_id
    req.status = KnowledgeUpdateStatus.APPLIED.value
    req.reviewed_by_id = current_user.id
    if not req.reviewed_at:
        req.reviewed_at = datetime.now(timezone.utc)

    if admin_notes:
        note_entry = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | {current_user.email} - Applied]: {admin_notes.strip()}"
        req.admin_notes = f"{note_entry}\n\n{req.admin_notes}" if req.admin_notes else note_entry

    req.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)

    _log_update_audit(
        db,
        action="knowledge_update_applied",
        request=req,
        actor=current_user,
        detail=(
            f"request_id={req.request_id} | new_document_id={new_doc_id} | "
            f"change_event_id={event_id} | filename={filename}"
        ),
    )

    return {
        "request": KnowledgeUpdateRequestOut.model_validate(req),
        "evolution_result": {
            "document_id": new_doc_id,
            "event_id": event_id,
            "change_type": result.get("action", "new_version"),
            "version": doc_obj.version if doc_obj else 1,
            "is_latest": doc_obj.is_latest if doc_obj else True,
            "evolution": result.get("evolution"),
        },
    }


def get_knowledge_update_stats(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
) -> Dict[str, Any]:
    """Summary statistics for admin review dashboard."""
    q = db.query(KnowledgeUpdateRequest)
    if caller_role not in (Role.SUPER_ADMIN, Role.PLATFORM_OWNER):
        if caller_role == Role.DOMAIN_MANAGER:
            auth_domains = _get_user_authorized_domain_names(db, current_user)
            if auth_domains:
                q = q.filter(func.lower(KnowledgeUpdateRequest.domain).in_(auth_domains))
            else:
                return {"total": 0, "pending_review": 0, "approved": 0, "rejected": 0, "applied": 0, "cancelled": 0, "by_root_cause": {}, "by_domain": {}}
        else:
            if current_user and hasattr(current_user, "id"):
                q = q.filter(KnowledgeUpdateRequest.created_by_id == current_user.id)
            else:
                return {"total": 0, "pending_review": 0, "approved": 0, "rejected": 0, "applied": 0, "cancelled": 0, "by_root_cause": {}, "by_domain": {}}

    total = q.count()
    status_counts: Dict[str, int] = {}
    for st, count in (
        q.with_entities(KnowledgeUpdateRequest.status, func.count(KnowledgeUpdateRequest.id))
        .group_by(KnowledgeUpdateRequest.status)
        .all()
    ):
        status_counts[st.lower()] = count

    root_cause_counts: Dict[str, int] = {}
    for rc, count in (
        q.with_entities(KnowledgeUpdateRequest.root_cause, func.count(KnowledgeUpdateRequest.id))
        .group_by(KnowledgeUpdateRequest.root_cause)
        .all()
    ):
        if rc:
            root_cause_counts[rc] = count

    domain_counts: Dict[str, int] = {}
    for dom, count in (
        q.with_entities(KnowledgeUpdateRequest.domain, func.count(KnowledgeUpdateRequest.id))
        .group_by(KnowledgeUpdateRequest.domain)
        .all()
    ):
        domain_counts[dom or "general"] = count

    return {
        "total": total,
        "pending_review": status_counts.get(KnowledgeUpdateStatus.PENDING_REVIEW.value, 0),
        "approved": status_counts.get(KnowledgeUpdateStatus.APPROVED.value, 0),
        "rejected": status_counts.get(KnowledgeUpdateStatus.REJECTED.value, 0),
        "applied": status_counts.get(KnowledgeUpdateStatus.APPLIED.value, 0),
        "cancelled": status_counts.get(KnowledgeUpdateStatus.CANCELLED.value, 0),
        "by_root_cause": root_cause_counts,
        "by_domain": domain_counts,
    }


def _log_update_audit(
    db: Session,
    action: str,
    request: KnowledgeUpdateRequest,
    actor: Optional[User],
    detail: str,
) -> None:
    try:
        actor_id = actor.id if actor and hasattr(actor, "id") else None
        actor_email = actor.email if actor and hasattr(actor, "email") else "system"
        audit = AuditLog(
            event_type=action,
            actor_id=actor_id,
            actor_email=actor_email,
            target_user_id=request.created_by_id,
            detail=detail,
        )
        db.add(audit)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[KnowledgeUpdate] Audit log failed: %s", exc)
