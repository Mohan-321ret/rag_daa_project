"""
Ingestion Job Service  –  Admin Panel: Data Injection Management
----------------------------------------------------------------------
Owns the IngestionJob lifecycle: creation, per-stage progress updates
(consumed as a callback by app/services/processing_pipeline.py and
app/services/evolution_service.py — see StageReporter below), retry,
cancel, and the dashboard's aggregate stats.

Threading model: POST /documents/upload creates the job using the
REQUEST's DB session (fast, synchronous — file validation + temp save +
job row), then hands the rest of the pipeline to a FastAPI BackgroundTask.
That background function runs in a worker thread (Starlette runs sync
callables via run_in_threadpool) and MUST open its own SQLAlchemy session
— the request's session is closed the moment the request returns, well
before the background task actually runs. StageReporter is constructed
with that background function's OWN session, never the request's.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.core.permissions import Role
from app.models.document import Document
from app.models.ingestion_job import JOB_STATUSES, PIPELINE_STAGES, STAGE_STATUSES, IngestionJob
from app.models.user import User
from app.services.domain_service import get_user_domain_ids, is_domain_unrestricted

logger = logging.getLogger(__name__)

# (stage_key, status, error_message) -> None
StageCallback = Callable[[str, str, Optional[str]], None]


def new_job_id() -> str:
    return f"JOB_{uuid.uuid4().hex[:10].upper()}"


def create_job(
    db: Session, *, original_filename: str, created_by_user_id,
    retry_of_job_id: Optional[str] = None, retry_count: int = 0,
) -> IngestionJob:
    job = IngestionJob(
        job_id=new_job_id(),
        original_filename=original_filename,
        status="queued",
        stage_log=json.dumps([]),
        created_by=created_by_user_id,
        retry_of_job_id=retry_of_job_id,
        retry_count=retry_count,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("[IngestionJob] 📥 Created %s for '%s' (retry_of=%s)", job.job_id, original_filename, retry_of_job_id)
    return job


class StageReporter:
    """
    A live-updating StageCallback bound to one job + DB session. Passed as
    `on_stage` into run_processing_pipeline()/process_document() — those
    modules have no idea an IngestionJob exists, they just call this
    callback at stage boundaries (dependency inversion: the pipeline stays
    reusable for the folder-watcher path, which doesn't pass a reporter).
    """

    def __init__(self, db: Session, job_id: str):
        self.db = db
        self.job_id = job_id

    def _load(self) -> Optional[IngestionJob]:
        return self.db.query(IngestionJob).filter(IngestionJob.job_id == self.job_id).first()

    def is_cancelled(self) -> bool:
        job = self._load()
        return job is not None and job.status == "cancelled"

    def __call__(self, stage: str, status: str, error: Optional[str] = None) -> None:
        if stage not in PIPELINE_STAGES or status not in STAGE_STATUSES:
            logger.warning("[IngestionJob] Ignoring unknown stage/status: %s/%s", stage, status)
            return
        job = self._load()
        if job is None:
            return
        try:
            log = json.loads(job.stage_log) if job.stage_log else []
        except (ValueError, TypeError):
            log = []

        now = datetime.now(timezone.utc).isoformat()
        if status == "running":
            log.append({"stage": stage, "status": "running", "started_at": now, "ended_at": None, "error": None})
            job.current_stage = stage
            if job.status == "queued":
                job.status = "processing"
        else:
            # Close out the most recent "running" entry for this stage.
            for entry in reversed(log):
                if entry["stage"] == stage and entry["status"] == "running":
                    entry["status"] = status
                    entry["ended_at"] = now
                    entry["error"] = error
                    break
            else:
                log.append({"stage": stage, "status": status, "started_at": now, "ended_at": now, "error": error})
            if status == "failed":
                job.status = "failed"
                job.error_message = error
                job.completed_at = datetime.now(timezone.utc)

        job.stage_log = json.dumps(log)
        self.db.commit()


def mark_completed(db: Session, job_id: str, document_id: str, action: Optional[str] = None) -> None:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
    if job is None:
        return
    job.status = "completed"
    job.document_id = document_id
    job.action = action
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("[IngestionJob] ✅ %s completed -> document=%s action=%s", job_id, document_id, action)


def mark_failed(db: Session, job_id: str, error: str) -> None:
    job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
    if job is None:
        return
    job.status = "failed"
    job.error_message = error
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.error("[IngestionJob] ❌ %s failed: %s", job_id, error)


def create_retry_job(db: Session, failed_job: IngestionJob, created_by_user_id) -> IngestionJob:
    """
    Create the NEW job row a retry runs under — full history is preserved
    (the original failed job row is never mutated/reused), linked via
    retry_of_job_id. Callers must have already verified failed_job.status ==
    'failed' and failed_job.document_id is set (see app/api/ingestion_jobs.py).
    """
    job = IngestionJob(
        job_id=new_job_id(),
        document_id=failed_job.document_id,
        original_filename=failed_job.original_filename,
        status="queued",
        stage_log=json.dumps([]),
        created_by=created_by_user_id,
        retry_of_job_id=failed_job.job_id,
        retry_count=failed_job.retry_count + 1,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "[IngestionJob] 🔁 Created retry %s (attempt #%d) of %s for document %s",
        job.job_id, job.retry_count, failed_job.job_id, failed_job.document_id,
    )
    return job


def run_retry_pipeline(job_id: str, document_id: str) -> None:
    """
    Background task body for a retry. Resumes from Document.extracted_text
    — the original file is NEVER stored, so re-extraction/re-OCR is not
    possible and not needed (see app/models/ingestion_job.py's module
    docstring). 'upload'/'document_loader'/'ocr' are reported as already
    settled since none of that work is repeated; the pipeline genuinely
    restarts from text_cleaning.

    Before reprocessing, any chunks left over from the failed attempt are
    torn down (Postgres rows deleted, FAISS vectors tombstoned) so a retry
    can never leave duplicate/orphaned chunks behind.

    Runs in a worker thread — opens its OWN DB session, same reasoning as
    app/api/documents.py's _run_ingestion_job().
    """
    from app.db.database import SessionLocal
    from app.models.chunk import Chunk
    from app.services.processing_pipeline import run_processing_pipeline
    from app.services.storage_service import StorageService
    from app.services.vector_store import get_vector_store

    db = SessionLocal()
    reporter = StageReporter(db, job_id)
    try:
        reporter("upload", "running")
        reporter("upload", "completed")
        reporter("document_loader", "running")
        reporter("document_loader", "completed")
        reporter("ocr", "skipped")

        storage = StorageService(db)
        document = storage.get_by_document_id(document_id)
        if document is None:
            raise RuntimeError(f"Document '{document_id}' no longer exists — cannot retry.")

        # ── Tear down chunks from the failed attempt ──────────────────────────
        old_chunks = storage.get_chunks(document_id)
        faiss_ids = [c.faiss_id for c in old_chunks if c.faiss_id is not None]
        if faiss_ids:
            get_vector_store().mark_deleted(faiss_ids)
            get_vector_store().save()
        if old_chunks:
            db.query(Chunk).filter(Chunk.document_id == document_id).delete()
            db.commit()
            logger.info(
                "[IngestionJob] 🧹 %s cleared %d stale chunk(s) from failed attempt",
                job_id, len(old_chunks),
            )

        run_processing_pipeline(
            document_id=document_id,
            raw_text=document.extracted_text or "",
            db=db,
            language_hint=document.language,
            on_stage=reporter,
        )

        mark_completed(db, job_id, document_id, action="retry")
        logger.info("[IngestionJob] 🎉 %s retry complete | document=%s", job_id, document_id)

    except Exception as exc:
        logger.error("[IngestionJob] ❌ retry %s failed: %s", job_id, exc)
        mark_failed(db, job_id, str(exc))
    finally:
        db.close()


def cancel_job(db: Session, job: IngestionJob) -> None:
    """
    Only meaningful for status='queued' — the narrow window between the
    upload response being accepted and the background task actually
    starting. Once any stage has begun, a job's execution is in another
    thread already mutating shared state (FAISS/Postgres) and cannot be
    safely interrupted, so cancel is refused (see app/api/ingestion_jobs.py)
    rather than pretending to stop something already in flight — "cancel
    processing where supported" is honored literally, not faked.
    """
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("[IngestionJob] 🛑 %s cancelled while queued", job.job_id)


def is_domain_scope_unrestricted_for_jobs(role: Role) -> bool:
    return is_domain_unrestricted(role)


def scope_jobs_for_user(query: Query, db: Session, user: User, role: Role) -> Query:
    """
    Domain-scoped roles (see domain_service) see: jobs they created
    themselves (covers jobs that never reached a Document row — nothing
    else to scope by yet), plus jobs whose resulting document falls in one
    of their own domains. Mirrors app/services/document_access_service.py's
    scope_document_list — same rule, applied to jobs instead of documents.
    """
    if is_domain_unrestricted(role):
        return query

    from sqlalchemy import or_
    domain_ids = get_user_domain_ids(db, user.id)
    conditions = [IngestionJob.created_by == user.id]
    if domain_ids:
        scoped_doc_ids = db.query(Document.document_id).filter(Document.domain_id.in_(domain_ids)).subquery()
        conditions.append(IngestionJob.document_id.in_(scoped_doc_ids))
    return query.filter(or_(*conditions))


def compute_stats(db: Session, user: User, role: Role) -> dict:
    base = scope_jobs_for_user(db.query(IngestionJob), db, user, role)

    counts = dict(base.with_entities(IngestionJob.status, func.count(IngestionJob.id)).group_by(IngestionJob.status).all())
    last_completed = (
        base.filter(IngestionJob.status == "completed")
        .order_by(IngestionJob.completed_at.desc())
        .first()
    )

    # "total documents" reflects the document registry itself (already
    # domain-scoped for read visibility — see document_access_service),
    # not the job table, since a document can only ever have one current
    # row regardless of how many job attempts/retries produced it.
    from app.services.document_access_service import scope_document_list
    total_documents = scope_document_list(db.query(Document), db, user, role).count()

    return {
        "total_documents": total_documents,
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
        "failed_ingestion_count": counts.get("failed", 0),
        "last_ingestion_at": last_completed.completed_at if last_completed else None,
    }
