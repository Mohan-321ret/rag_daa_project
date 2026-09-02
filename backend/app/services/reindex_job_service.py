"""
Reindex Job Service  –  Admin Panel: Chunk Indexing Management
----------------------------------------------------------------------
Owns the ReindexJob lifecycle (creation, progress updates, completion,
cancellation) and the dashboard's aggregate stats — the exact counterpart
of app/services/ingestion_job_service.py for indexing operations instead
of ingestion. See app/models/reindex_job.py's module docstring for why
this uses a simple processed/total counter instead of ingestion's
per-stage stage_log.

Threading model: identical to ingestion_job_service.py — the API layer
creates the job row using the REQUEST's DB session (fast/synchronous),
then hands the actual work to a FastAPI BackgroundTask. That background
function (in app/services/chunk_indexing_service.py) MUST open its own
SQLAlchemy session, since the request's session closes the instant the
request returns.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.core.permissions import Role
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.reindex_job import ReindexJob
from app.models.user import User
from app.services.document_access_service import scope_document_list
from app.services.domain_service import get_user_domain_ids, is_domain_unrestricted

logger = logging.getLogger(__name__)


def new_job_id() -> str:
    return f"RIJ_{uuid.uuid4().hex[:10].upper()}"


def create_job(
    db: Session, *, job_type: str, created_by_user_id,
    scope_document_id: Optional[str] = None, scope_domain_id: Optional[str] = None,
    scope_chunk_ids: Optional[list] = None, total_items: int = 0,
) -> ReindexJob:
    job = ReindexJob(
        job_id=new_job_id(),
        job_type=job_type,
        status="queued",
        scope_document_id=scope_document_id,
        scope_domain_id=scope_domain_id,
        scope_chunk_ids=json.dumps(scope_chunk_ids) if scope_chunk_ids is not None else None,
        total_items=total_items,
        error_log=json.dumps([]),
        created_by=created_by_user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "[ReindexJob] 📥 Created %s type=%s total_items=%d", job.job_id, job_type, total_items,
    )
    return job


class ProgressReporter:
    """
    A live-updating progress callback bound to one job + DB session —
    passed into chunk_indexing_service.py's per-item reindex loop, the
    same dependency-inversion shape as ingestion_job_service.StageReporter.
    """

    def __init__(self, db: Session, job_id: str):
        self.db = db
        self.job_id = job_id

    def _load(self) -> Optional[ReindexJob]:
        return self.db.query(ReindexJob).filter(ReindexJob.job_id == self.job_id).first()

    def is_cancelled(self) -> bool:
        job = self._load()
        return job is not None and job.status == "cancelled"

    def start(self) -> None:
        job = self._load()
        if job is None:
            return
        job.status = "processing"
        self.db.commit()

    def advance(self, *, success: bool, ref: str, error: Optional[str] = None) -> None:
        job = self._load()
        if job is None:
            return
        job.processed_items += 1
        if not success:
            job.failed_items += 1
            try:
                log = json.loads(job.error_log) if job.error_log else []
            except (ValueError, TypeError):
                log = []
            log.append({"ref": ref, "error": error, "at": datetime.now(timezone.utc).isoformat()})
            job.error_log = json.dumps(log)
        self.db.commit()


def mark_completed(db: Session, job_id: str) -> None:
    job = db.query(ReindexJob).filter(ReindexJob.job_id == job_id).first()
    if job is None:
        return
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        "[ReindexJob] ✅ %s completed | processed=%d failed=%d",
        job_id, job.processed_items, job.failed_items,
    )


def mark_failed(db: Session, job_id: str, error: str) -> None:
    job = db.query(ReindexJob).filter(ReindexJob.job_id == job_id).first()
    if job is None:
        return
    job.status = "failed"
    job.error_message = error
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.error("[ReindexJob] ❌ %s failed: %s", job_id, error)


def cancel_job(db: Session, job: ReindexJob) -> None:
    """Only meaningful for status='queued' — same narrow window/rationale as ingestion_job_service.cancel_job."""
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("[ReindexJob] 🛑 %s cancelled while queued", job.job_id)


def scope_jobs_for_user(query: Query, db: Session, user: User, role: Role) -> Query:
    """
    Domain-scoped roles see: jobs they created themselves, jobs scoped to
    one of their own domains (scope_domain_id), or jobs scoped to a
    document that falls in one of their own domains (scope_document_id).
    Mirrors ingestion_job_service.scope_jobs_for_user.
    """
    if is_domain_unrestricted(role):
        return query

    from sqlalchemy import or_
    domain_ids = get_user_domain_ids(db, user.id)
    conditions = [ReindexJob.created_by == user.id]
    if domain_ids:
        conditions.append(ReindexJob.scope_domain_id.in_(domain_ids))
        scoped_doc_ids = db.query(Document.document_id).filter(Document.domain_id.in_(domain_ids)).subquery()
        conditions.append(ReindexJob.scope_document_id.in_(scoped_doc_ids))
    return query.filter(or_(*conditions))


def scope_chunks_for_user(query: Query, db: Session, user: User, role: Role) -> Query:
    """
    Filter a Chunk query down to chunks belonging to documents *user* is
    allowed to see — reuses document_access_service.scope_document_list
    (global/domain/restricted semantics already fully implemented and
    tested there) rather than re-deriving chunk-level scoping rules.
    """
    if is_domain_unrestricted(role):
        return query
    visible_doc_ids = scope_document_list(db.query(Document.document_id), db, user, role).subquery()
    return query.filter(Chunk.document_id.in_(visible_doc_ids))


def compute_stats(db: Session, user: User, role: Role) -> dict:
    from app.core.config import settings
    from app.services.vector_store import get_vector_store

    base = scope_chunks_for_user(db.query(Chunk), db, user, role)
    counts = dict(base.with_entities(Chunk.index_status, func.count(Chunk.id)).group_by(Chunk.index_status).all())
    total_chunks = sum(counts.values())
    last_indexed = base.with_entities(func.max(Chunk.indexed_at)).scalar()

    store = get_vector_store()
    try:
        faiss_total = store.total
        faiss_active = store.active_total
        index_status = "operational"
    except Exception as exc:  # pragma: no cover — FAISS I/O failure
        logger.error("[ReindexJob] FAISS store unavailable for stats: %s", exc)
        faiss_total = faiss_active = 0
        index_status = "unavailable"

    return {
        "total_chunks": total_chunks,
        "indexed_chunks": counts.get("indexed", 0),
        "pending_chunks": counts.get("pending", 0),
        "failed_chunks": counts.get("failed", 0),
        "stale_chunks": counts.get("stale", 0),
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "index_status": index_status,
        "faiss_total_vectors": faiss_total,
        "faiss_active_vectors": faiss_active,
        "last_indexing_time": last_indexed,
    }
