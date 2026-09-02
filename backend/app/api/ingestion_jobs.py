"""
Ingestion Jobs API Router  –  Admin Panel: Data Injection Management
----------------------------------------------------------------------
Read/control surface for the async ingestion jobs created by
POST /documents/upload (see app/api/documents.py). Everything here is a
thin layer over app/services/ingestion_job_service.py:

  GET  /ingestion-jobs           – list jobs (domain-scoped, filterable)
  GET  /ingestion-jobs/stats     – dashboard aggregate counts
  GET  /ingestion-jobs/{job_id}  – single job detail incl. full stage_log
  POST /ingestion-jobs/{job_id}/retry   – re-run a failed job from extracted_text
  POST /ingestion-jobs/{job_id}/cancel  – cancel a still-queued job

Gated by Permission.INGESTION_MONITOR (read) / INGESTION_RETRY (retry,
cancel) — both already existed in the Phase 2 Role & Access Matrix, unused
until now.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.ingestion_job import JOB_STATUSES, IngestionJob
from app.models.user import User
from app.schemas.ingestion_job import (
    CancelJobResponse,
    IngestionJobListResponse,
    IngestionJobOut,
    IngestionJobStatsResponse,
    RetryJobResponse,
)
from app.services import ingestion_job_service
from app.services.auth_service import current_role, require_permission

router = APIRouter(prefix="/ingestion-jobs", tags=["Data Injection Management"])


def _to_out(job: IngestionJob) -> IngestionJobOut:
    try:
        stage_log = json.loads(job.stage_log) if job.stage_log else []
    except (ValueError, TypeError):
        stage_log = []
    return IngestionJobOut(
        job_id=job.job_id,
        document_id=job.document_id,
        original_filename=job.original_filename,
        status=job.status,
        current_stage=job.current_stage,
        stage_log=stage_log,
        error_message=job.error_message,
        action=job.action,
        retry_of_job_id=job.retry_of_job_id,
        retry_count=job.retry_count,
        created_by=str(job.created_by) if job.created_by else None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def _get_visible_job(db: Session, user: User, role: Role, job_id: str) -> IngestionJob:
    """
    Fetch a job by job_id, scoped to what *user* is allowed to see (mirrors
    document_access_service's pattern). Returns 404 rather than 403 for an
    out-of-scope job so existence isn't leaked to unauthorized callers.
    """
    query = ingestion_job_service.scope_jobs_for_user(
        db.query(IngestionJob).filter(IngestionJob.job_id == job_id), db, user, role,
    )
    job = query.first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ingestion job '{job_id}' not found.")
    return job


# ── GET /ingestion-jobs ────────────────────────────────────────────────────────

@router.get("/", response_model=IngestionJobListResponse, summary="List ingestion jobs")
def list_ingestion_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
    caller_role: Role = Depends(current_role),
    job_status: Optional[str] = Query(default=None, alias="status", description=f"Filter: one of {JOB_STATUSES}"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> IngestionJobListResponse:
    query = ingestion_job_service.scope_jobs_for_user(db.query(IngestionJob), db, current_user, caller_role)
    if job_status:
        if job_status not in JOB_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown status: {job_status}")
        query = query.filter(IngestionJob.status == job_status)

    total = query.count()
    rows = query.order_by(IngestionJob.created_at.desc()).offset(skip).limit(limit).all()
    return IngestionJobListResponse(total=total, skip=skip, limit=limit, jobs=[_to_out(r) for r in rows])


# ── GET /ingestion-jobs/stats ──────────────────────────────────────────────────

@router.get("/stats", response_model=IngestionJobStatsResponse, summary="Data Injection Dashboard stats")
def get_ingestion_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
    caller_role: Role = Depends(current_role),
) -> IngestionJobStatsResponse:
    return IngestionJobStatsResponse(**ingestion_job_service.compute_stats(db, current_user, caller_role))


# ── GET /ingestion-jobs/{job_id} ───────────────────────────────────────────────

@router.get("/{job_id}", response_model=IngestionJobOut, summary="Inspect a single ingestion job")
def get_ingestion_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
    caller_role: Role = Depends(current_role),
) -> IngestionJobOut:
    job = _get_visible_job(db, current_user, caller_role, job_id)
    return _to_out(job)


# ── POST /ingestion-jobs/{job_id}/retry ────────────────────────────────────────

@router.post("/{job_id}/retry", response_model=RetryJobResponse, summary="Retry a failed ingestion job")
def retry_ingestion_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_RETRY)),
    caller_role: Role = Depends(current_role),
) -> RetryJobResponse:
    job = _get_visible_job(db, current_user, caller_role, job_id)
    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only failed jobs can be retried (current status: '{job.status}').",
        )
    if not job.document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This job failed before any text was extracted, so there is "
                "nothing saved to retry from (the original file is never "
                "stored). Please re-upload the document."
            ),
        )

    retry_job = ingestion_job_service.create_retry_job(db, job, created_by_user_id=current_user.id)
    background_tasks.add_task(
        ingestion_job_service.run_retry_pipeline, job_id=retry_job.job_id, document_id=job.document_id,
    )
    return RetryJobResponse(job_id=retry_job.job_id, retry_of_job_id=job.job_id, status=retry_job.status)


# ── POST /ingestion-jobs/{job_id}/cancel ───────────────────────────────────────

@router.post("/{job_id}/cancel", response_model=CancelJobResponse, summary="Cancel a queued ingestion job")
def cancel_ingestion_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.INGESTION_RETRY)),
    caller_role: Role = Depends(current_role),
) -> CancelJobResponse:
    job = _get_visible_job(db, current_user, caller_role, job_id)
    if job.status != "queued":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Only queued jobs can be cancelled (current status: '{job.status}'). "
                "Processing already in progress cannot be safely interrupted."
            ),
        )
    ingestion_job_service.cancel_job(db, job)
    return CancelJobResponse(success=True, job_id=job.job_id, status=job.status, message="Job cancelled.")
