"""
Chunk Indexing API Router  –  Admin Panel: Chunk Indexing Management
----------------------------------------------------------------------
Inspect/search/filter chunks, and trigger (async, background-job-backed —
see app/services/chunk_indexing_service.py) re-indexing operations:

  GET  /chunk-indexing/stats                       – dashboard stats
  GET  /chunk-indexing/chunks                      – inspect/search/filter
  GET  /chunk-indexing/jobs                        – job history (domain-scoped)
  GET  /chunk-indexing/jobs/{job_id}                – job detail incl. errors
  POST /chunk-indexing/reindex/chunks               – re-index selected chunks
  POST /chunk-indexing/reindex/document/{doc_id}    – re-index a document
  POST /chunk-indexing/reindex/domain/{domain_id}   – re-index a domain
  POST /chunk-indexing/retry-failed                 – retry failed chunks
  POST /chunk-indexing/remove-stale                 – tombstone stale vectors
  POST /chunk-indexing/rebuild                      – full index rebuild
  POST /chunk-indexing/jobs/{job_id}/cancel         – cancel a queued job

Gated by Permission.CHUNK_VIEW (read) / CHUNK_REINDEX (all maintenance
actions) / CHUNK_REBUILD_INDEX (full rebuild only) — all three already
existed in the Phase 2 Role & Access Matrix, unenforced until now.

"Do not allow unauthorized users to manipulate another domain's index":
every domain/document-scoped write below re-validates the caller's domain
membership even though they already hold CHUNK_REINDEX at the role level —
holding the permission means "can manage indexing", not "can manage every
domain's indexing". A full rebuild is stricter still: it touches every
domain's vectors at once, so it additionally requires a domain-UNRESTRICTED
role, regardless of whether the caller's role nominally lists
CHUNK_REBUILD_INDEX (DOMAIN_MANAGER does, in the Phase 2 matrix — see the
dedicated check in rebuild_index() below for why that's not enough here).

Every trigger endpoint (including cancel) writes one AuditLog row
(chunk_index_triggered / chunk_index_cancelled) — "Add audit logs for
indexing operations."
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.chunk import CHUNK_INDEX_STATUSES, Chunk
from app.models.document import Document
from app.models.domain import Domain
from app.models.reindex_job import REINDEX_JOB_STATUSES, ReindexJob
from app.models.user import User
from app.schemas.chunk_indexing import (
    CancelReindexJobResponse,
    ChunkIndexStatsResponse,
    ChunkInspectListResponse,
    ChunkInspectOut,
    ReindexAcceptedResponse,
    ReindexChunksRequest,
    ReindexJobListResponse,
    ReindexJobOut,
)
from app.services import chunk_indexing_service, reindex_job_service
from app.services.audit_service import log_audit_event
from app.services.auth_service import current_role, require_permission
from app.services.document_access_service import assert_document_visible, scope_document_list
from app.services.domain_service import get_user_domain_ids, is_domain_unrestricted

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chunk-indexing", tags=["Chunk Indexing Management"])


# ── Authorization helpers ───────────────────────────────────────────────────

def _assert_domain_manageable(db: Session, user: User, role: Role, domain_id: str) -> None:
    """A domain-scoped caller may only trigger index operations for a domain they belong to."""
    if is_domain_unrestricted(role):
        return
    if domain_id not in get_user_domain_ids(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot manage the index for a domain you do not belong to.",
        )


def _get_document_or_404(db: Session, document_id: str) -> Document:
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_id}' not found.")
    return doc


def _get_domain_or_404(db: Session, domain_id: str) -> Domain:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Domain '{domain_id}' not found.")
    return domain


def _job_to_out(job: ReindexJob) -> ReindexJobOut:
    try:
        error_log = json.loads(job.error_log) if job.error_log else []
    except (ValueError, TypeError):
        error_log = []
    try:
        chunk_ids = json.loads(job.scope_chunk_ids) if job.scope_chunk_ids else None
    except (ValueError, TypeError):
        chunk_ids = None
    return ReindexJobOut(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        scope_document_id=job.scope_document_id,
        scope_domain_id=str(job.scope_domain_id) if job.scope_domain_id else None,
        scope_chunk_ids=chunk_ids,
        total_items=job.total_items,
        processed_items=job.processed_items,
        failed_items=job.failed_items,
        error_log=error_log,
        error_message=job.error_message,
        created_by=str(job.created_by) if job.created_by else None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def _get_visible_job(db: Session, user: User, role: Role, job_id: str) -> ReindexJob:
    query = reindex_job_service.scope_jobs_for_user(
        db.query(ReindexJob).filter(ReindexJob.job_id == job_id), db, user, role,
    )
    job = query.first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Reindex job '{job_id}' not found.")
    return job


def _audit(db: Session, event_type: str, actor: User, detail: str) -> None:
    log_audit_event(db, event_type=event_type, actor=actor, detail=detail)
    db.commit()


# ── GET /chunk-indexing/stats ───────────────────────────────────────────────

@router.get("/stats", response_model=ChunkIndexStatsResponse, summary="Chunk Indexing Dashboard stats")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
) -> ChunkIndexStatsResponse:
    return ChunkIndexStatsResponse(**reindex_job_service.compute_stats(db, current_user, caller_role))


# ── GET /chunk-indexing/chunks ──────────────────────────────────────────────

@router.get("/chunks", response_model=ChunkInspectListResponse, summary="Inspect / search / filter chunks")
def list_chunks(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
    q: Optional[str] = Query(default=None, description="Substring search over chunk text"),
    domain_id: Optional[str] = Query(default=None),
    document_id: Optional[str] = Query(default=None),
    version: Optional[int] = Query(default=None, description="Filter by document_version"),
    status_filter: Optional[str] = Query(default=None, alias="status", description=f"One of {CHUNK_INDEX_STATUSES}"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ChunkInspectListResponse:
    query = reindex_job_service.scope_chunks_for_user(db.query(Chunk), db, current_user, caller_role)
    if q:
        query = query.filter(Chunk.text.ilike(f"%{q}%"))
    if domain_id:
        query = query.filter(Chunk.domain_id == domain_id)
    if document_id:
        query = query.filter(Chunk.document_id == document_id)
    if version is not None:
        query = query.filter(Chunk.document_version == version)
    if status_filter:
        if status_filter not in CHUNK_INDEX_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown status: {status_filter}")
        query = query.filter(Chunk.index_status == status_filter)

    total = query.count()
    rows = query.order_by(Chunk.document_id, Chunk.chunk_index).offset(skip).limit(limit).all()
    return ChunkInspectListResponse(total=total, skip=skip, limit=limit, chunks=[ChunkInspectOut.model_validate(c) for c in rows])


# ── GET /chunk-indexing/jobs ────────────────────────────────────────────────

@router.get("/jobs", response_model=ReindexJobListResponse, summary="List reindex jobs")
def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
    job_status: Optional[str] = Query(default=None, alias="status", description=f"Filter: one of {REINDEX_JOB_STATUSES}"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ReindexJobListResponse:
    query = reindex_job_service.scope_jobs_for_user(db.query(ReindexJob), db, current_user, caller_role)
    if job_status:
        if job_status not in REINDEX_JOB_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown status: {job_status}")
        query = query.filter(ReindexJob.status == job_status)

    total = query.count()
    rows = query.order_by(ReindexJob.created_at.desc()).offset(skip).limit(limit).all()
    return ReindexJobListResponse(total=total, skip=skip, limit=limit, jobs=[_job_to_out(r) for r in rows])


@router.get("/jobs/{job_id}", response_model=ReindexJobOut, summary="Inspect a single reindex job")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
) -> ReindexJobOut:
    return _job_to_out(_get_visible_job(db, current_user, caller_role, job_id))


# ── POST /chunk-indexing/reindex/chunks ─────────────────────────────────────

@router.post("/reindex/chunks", response_model=ReindexAcceptedResponse, status_code=status.HTTP_202_ACCEPTED, summary="Re-index selected chunks")
def reindex_chunks(
    body: ReindexChunksRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
) -> ReindexAcceptedResponse:
    chunks = db.query(Chunk).filter(Chunk.id.in_(body.chunk_ids)).all()
    found_ids = {str(c.id) for c in chunks}
    missing = [cid for cid in body.chunk_ids if cid not in found_ids]
    if missing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chunk id(s) not found: {missing}")

    if not is_domain_unrestricted(caller_role):
        authorized_doc_ids = {
            row[0] for row in scope_document_list(db.query(Document.document_id), db, current_user, caller_role).all()
        }
        out_of_scope = {c.document_id for c in chunks} - authorized_doc_ids
        if out_of_scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="One or more selected chunks belong to a document you cannot manage.",
            )

    # Stale chunks can't be "re-indexed" — see chunk_indexing_service.py's
    # module comment. Silently drop them from an otherwise-valid selection;
    # only fail the request if EVERY selected chunk turned out to be stale.
    active_chunk_ids = [str(c.id) for c in chunks if c.index_status != "stale"]
    if not active_chunk_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All selected chunks are stale (superseded). Use remove-stale instead of reindexing them.",
        )

    job = reindex_job_service.create_job(
        db, job_type="chunks", created_by_user_id=current_user.id,
        scope_chunk_ids=active_chunk_ids, total_items=len(active_chunk_ids),
    )
    background_tasks.add_task(chunk_indexing_service.run_reindex_chunks_job, job_id=job.job_id, chunk_ids=active_chunk_ids)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=chunks count={len(active_chunk_ids)}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="chunks", total_items=len(active_chunk_ids))


# ── POST /chunk-indexing/reindex/document/{document_id} ────────────────────

@router.post(
    "/reindex/document/{document_id}", response_model=ReindexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED, summary="Re-index every chunk of a document",
)
def reindex_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
) -> ReindexAcceptedResponse:
    doc = _get_document_or_404(db, document_id)
    assert_document_visible(db, current_user, caller_role, doc)

    total = db.query(Chunk).filter(Chunk.document_id == document_id, Chunk.index_status != "stale").count()
    job = reindex_job_service.create_job(
        db, job_type="document", created_by_user_id=current_user.id,
        scope_document_id=document_id, total_items=total,
    )
    background_tasks.add_task(chunk_indexing_service.run_reindex_document_job, job_id=job.job_id, document_id=document_id)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=document document_id={document_id} count={total}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="document", total_items=total)


# ── POST /chunk-indexing/reindex/domain/{domain_id} ─────────────────────────

@router.post(
    "/reindex/domain/{domain_id}", response_model=ReindexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED, summary="Re-index every chunk in a domain",
)
def reindex_domain(
    domain_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
) -> ReindexAcceptedResponse:
    _get_domain_or_404(db, domain_id)
    _assert_domain_manageable(db, current_user, caller_role, domain_id)

    total = db.query(Chunk).filter(Chunk.domain_id == domain_id, Chunk.index_status != "stale").count()
    job = reindex_job_service.create_job(
        db, job_type="domain", created_by_user_id=current_user.id,
        scope_domain_id=domain_id, total_items=total,
    )
    background_tasks.add_task(chunk_indexing_service.run_reindex_domain_job, job_id=job.job_id, domain_id=domain_id)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=domain domain_id={domain_id} count={total}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="domain", total_items=total)


# ── POST /chunk-indexing/retry-failed ───────────────────────────────────────

@router.post(
    "/retry-failed", response_model=ReindexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED, summary="Retry every failed chunk in scope",
)
def retry_failed(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
    document_id: Optional[str] = Query(default=None),
    domain_id: Optional[str] = Query(default=None),
) -> ReindexAcceptedResponse:
    if document_id:
        assert_document_visible(db, current_user, caller_role, _get_document_or_404(db, document_id))
    if domain_id:
        _get_domain_or_404(db, domain_id)
        _assert_domain_manageable(db, current_user, caller_role, domain_id)

    query = reindex_job_service.scope_chunks_for_user(db.query(Chunk), db, current_user, caller_role).filter(Chunk.index_status == "failed")
    if document_id:
        query = query.filter(Chunk.document_id == document_id)
    if domain_id:
        query = query.filter(Chunk.domain_id == domain_id)
    total = query.count()

    job = reindex_job_service.create_job(
        db, job_type="retry_failed", created_by_user_id=current_user.id,
        scope_document_id=document_id, scope_domain_id=domain_id, total_items=total,
    )
    background_tasks.add_task(chunk_indexing_service.run_retry_failed_job, job_id=job.job_id, document_id=document_id, domain_id=domain_id)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=retry_failed document_id={document_id} domain_id={domain_id} count={total}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="retry_failed", total_items=total)


# ── POST /chunk-indexing/remove-stale ───────────────────────────────────────

@router.post(
    "/remove-stale", response_model=ReindexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED, summary="Tombstone stale vectors in scope",
)
def remove_stale(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
    document_id: Optional[str] = Query(default=None),
    domain_id: Optional[str] = Query(default=None),
) -> ReindexAcceptedResponse:
    if document_id:
        assert_document_visible(db, current_user, caller_role, _get_document_or_404(db, document_id))
    if domain_id:
        _get_domain_or_404(db, domain_id)
        _assert_domain_manageable(db, current_user, caller_role, domain_id)

    query = (
        reindex_job_service.scope_chunks_for_user(db.query(Chunk), db, current_user, caller_role)
        .filter(Chunk.index_status == "stale", Chunk.faiss_id.isnot(None))
    )
    if document_id:
        query = query.filter(Chunk.document_id == document_id)
    if domain_id:
        query = query.filter(Chunk.domain_id == domain_id)
    total = query.count()

    job = reindex_job_service.create_job(
        db, job_type="remove_stale", created_by_user_id=current_user.id,
        scope_document_id=document_id, scope_domain_id=domain_id, total_items=total,
    )
    background_tasks.add_task(chunk_indexing_service.run_remove_stale_job, job_id=job.job_id, document_id=document_id, domain_id=domain_id)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=remove_stale document_id={document_id} domain_id={domain_id} count={total}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="remove_stale", total_items=total)


# ── POST /chunk-indexing/rebuild ────────────────────────────────────────────

@router.post(
    "/rebuild", response_model=ReindexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED, summary="Rebuild the full vector index from scratch",
)
def rebuild_index(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REBUILD_INDEX)),
    caller_role: Role = Depends(current_role),
) -> ReindexAcceptedResponse:
    # A full rebuild touches every domain's vectors in one operation — even
    # though DOMAIN_MANAGER nominally holds CHUNK_REBUILD_INDEX in the Phase
    # 2 matrix, "if authorized" for THIS action means domain-unrestricted,
    # matching "do not allow unauthorized users to manipulate another
    # domain's index" for the one operation that can't be scoped to a
    # single domain by definition.
    if not is_domain_unrestricted(caller_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A full index rebuild affects every domain's index and is restricted to platform-wide administrators.",
        )

    total = (
        db.query(Chunk)
        .join(Document, Chunk.document_id == Document.document_id)
        .filter(Document.is_latest.is_(True))
        .count()
    )
    job = reindex_job_service.create_job(
        db, job_type="full_rebuild", created_by_user_id=current_user.id, total_items=total,
    )
    background_tasks.add_task(chunk_indexing_service.run_full_rebuild_job, job_id=job.job_id)
    _audit(db, "chunk_index_triggered", current_user, f"job={job.job_id} type=full_rebuild count={total}")
    return ReindexAcceptedResponse(job_id=job.job_id, job_type="full_rebuild", total_items=total)


# ── POST /chunk-indexing/jobs/{job_id}/cancel ───────────────────────────────

@router.post("/jobs/{job_id}/cancel", response_model=CancelReindexJobResponse, summary="Cancel a queued reindex job")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
    caller_role: Role = Depends(current_role),
) -> CancelReindexJobResponse:
    job = _get_visible_job(db, current_user, caller_role, job_id)
    if job.status != "queued":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only queued jobs can be cancelled (current status: '{job.status}').",
        )
    reindex_job_service.cancel_job(db, job)
    _audit(db, "chunk_index_cancelled", current_user, f"job={job.job_id} type={job.job_type}")
    return CancelReindexJobResponse(success=True, job_id=job.job_id, status=job.status, message="Job cancelled.")
