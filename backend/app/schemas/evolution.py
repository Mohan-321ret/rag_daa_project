"""
Pydantic schemas for the Knowledge Evolution Engine API (Module 3 – Phase 6).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ── Change events ─────────────────────────────────────────────────────────────

class ChangeEventSummary(BaseModel):
    """One row of the evolution timeline."""
    event_id: str
    change_type: str                       # new_document | new_version | unchanged
    filename: str
    old_document_id: Optional[str] = None
    new_document_id: Optional[str] = None
    version_from: Optional[int] = None
    version_to: Optional[int] = None
    source: str = "upload"
    text_similarity: Optional[float] = None
    embedding_similarity: Optional[float] = None
    drift_detected: bool = False
    conflict_count: int = 0
    chunks_added: int = 0
    chunks_removed: int = 0
    chunks_unchanged: int = 0
    detected_at: datetime

    model_config = {"from_attributes": True}


class ChangeEventDetail(ChangeEventSummary):
    """Full evolution event, including diff, drifted chunks and conflicts."""
    lines_added: int = 0
    lines_removed: int = 0
    lines_modified: int = 0
    unified_diff: Optional[str] = None
    drifted_chunks: List[dict] = Field(default_factory=list)
    conflicts: List[dict] = Field(default_factory=list)
    embeddings_reused: int = 0
    embeddings_computed: int = 0


class ChangeEventListResponse(BaseModel):
    total: int
    events: List[ChangeEventSummary]


# ── Ad-hoc comparison ─────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    old_document_id: str = Field(..., examples=["DOC_3F2A1B9C"])
    new_document_id: str = Field(..., examples=["DOC_9E4D2A71"])


class CompareResponse(BaseModel):
    old_document_id: str
    new_document_id: str
    diff: dict
    drift: dict
    conflicts: List[dict]
    conflict_count: int


# ── Version history ───────────────────────────────────────────────────────────

class VersionInfo(BaseModel):
    document_id: str
    version: int
    is_latest: bool
    content_hash: Optional[str] = None
    previous_version_id: Optional[str] = None
    word_count: int
    processing_status: str
    upload_date: datetime

    model_config = {"from_attributes": True}


class VersionHistoryResponse(BaseModel):
    original_filename: str
    total_versions: int
    versions: List[VersionInfo]


# ── Watcher control ───────────────────────────────────────────────────────────

class WatcherStatusResponse(BaseModel):
    running: bool
    watch_dir: str
    poll_interval_s: int
    last_scan: Optional[str] = None
    files_tracked: int = 0
    files_ingested: int = 0
    recent_events: List[Any] = Field(default_factory=list)
