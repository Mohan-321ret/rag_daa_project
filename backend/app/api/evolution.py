"""
Knowledge Evolution API Router  –  Phase 6 Module 3
-----------------------------------------------------
Endpoints:
  GET  /evolution/changes                – evolution timeline (all change events)
  GET  /evolution/changes/{event_id}     – full event detail (diff/drift/conflicts)
  GET  /evolution/versions/{document_id} – version history of a document lineage
  POST /evolution/compare                – ad-hoc comparison of two documents
  GET  /evolution/watcher                – folder watcher status
  POST /evolution/watcher/start          – start the folder watcher
  POST /evolution/watcher/stop           – stop the folder watcher
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db.database import get_db
from app.models.document_change import DocumentChange
from app.models.user import User
from app.services.auth_service import require_permission
from app.schemas.evolution import (
    ChangeEventDetail,
    ChangeEventListResponse,
    ChangeEventSummary,
    CompareRequest,
    CompareResponse,
    VersionHistoryResponse,
    VersionInfo,
    WatcherStatusResponse,
)
from app.services.change_monitor import get_folder_watcher
from app.services.evolution_service import compare_documents, get_version_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evolution", tags=["Knowledge Evolution (Module 3)"])


# ── Change events ─────────────────────────────────────────────────────────────

@router.get(
    "/changes",
    response_model=ChangeEventListResponse,
    summary="List knowledge evolution events",
)
def list_changes(
    skip: int = 0,
    limit: int = Query(default=20, le=100),
    change_type: str | None = Query(
        default=None, description="Filter: new_document | new_version | unchanged"
    ),
    document_id: str | None = Query(
        default=None, description="Filter events involving this document ID"
    ),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
) -> ChangeEventListResponse:
    """Return the evolution timeline, newest events first."""
    q = db.query(DocumentChange)
    if change_type:
        q = q.filter(DocumentChange.change_type == change_type)
    if document_id:
        q = q.filter(
            (DocumentChange.old_document_id == document_id)
            | (DocumentChange.new_document_id == document_id)
        )
    total = q.count()
    rows = (
        q.order_by(DocumentChange.detected_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return ChangeEventListResponse(
        total=total,
        events=[ChangeEventSummary.model_validate(r) for r in rows],
    )


@router.get(
    "/changes/{event_id}",
    response_model=ChangeEventDetail,
    summary="Get full detail of one evolution event",
)
def get_change(
    event_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
) -> ChangeEventDetail:
    """Return diff, drifted chunks, conflicts, and reindex stats for an event."""
    row = (
        db.query(DocumentChange)
        .filter(DocumentChange.event_id == event_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Change event '{event_id}' not found.",
        )

    def _json_list(value: str | None) -> list:
        if not value:
            return []
        try:
            return json.loads(value)
        except ValueError:
            return []

    # Build from a dict: drifted_chunks / conflicts are JSON strings in the DB
    data = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    data["drifted_chunks"] = _json_list(row.drifted_chunks)
    data["conflicts"] = _json_list(row.conflicts)
    return ChangeEventDetail.model_validate(data)


# ── Version history ───────────────────────────────────────────────────────────

@router.get(
    "/versions/{document_id}",
    response_model=VersionHistoryResponse,
    summary="Get the version history of a document lineage",
)
def version_history(
    document_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.DOCUMENT_VERSION_MANAGE)),
) -> VersionHistoryResponse:
    """All versions sharing the given document's original filename."""
    versions = get_version_history(db, document_id)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    return VersionHistoryResponse(
        original_filename=versions[0].original_filename,
        total_versions=len(versions),
        versions=[VersionInfo.model_validate(v) for v in versions],
    )


# ── Ad-hoc comparison ─────────────────────────────────────────────────────────

@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="Compare two ingested documents (diff + drift + conflicts)",
)
def compare(
    body: CompareRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.DOCUMENT_VERSION_MANAGE)),
) -> CompareResponse:
    """Run Steps 2–4 of the evolution pipeline between any two documents."""
    try:
        result = compare_documents(db, body.old_document_id, body.new_document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return CompareResponse(**result)


# ── Folder watcher control ────────────────────────────────────────────────────

@router.get(
    "/watcher",
    response_model=WatcherStatusResponse,
    summary="Folder watcher status (Step 1 – Document Change Monitor)",
)
def watcher_status(
    _: User = Depends(require_permission(Permission.INGESTION_MONITOR)),
) -> WatcherStatusResponse:
    return WatcherStatusResponse(**get_folder_watcher().status())


@router.post(
    "/watcher/start",
    response_model=WatcherStatusResponse,
    summary="Start the folder watcher",
)
def watcher_start(
    _: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
) -> WatcherStatusResponse:
    watcher = get_folder_watcher()
    started = watcher.start()
    logger.info("[Evolution API] Watcher start requested (started=%s)", started)
    return WatcherStatusResponse(**watcher.status())


@router.post(
    "/watcher/stop",
    response_model=WatcherStatusResponse,
    summary="Stop the folder watcher",
)
async def watcher_stop(
    _: User = Depends(require_permission(Permission.CHUNK_REINDEX)),
) -> WatcherStatusResponse:
    watcher = get_folder_watcher()
    await watcher.stop()
    return WatcherStatusResponse(**watcher.status())
