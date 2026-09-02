"""
Pydantic schemas for the Ingestion Job API — Admin Panel: Data Injection
Management. Separates the async job API contract from the IngestionJob
ORM model.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StageLogEntry(BaseModel):
    stage: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error: Optional[str] = None


class UploadAcceptedResponse(BaseModel):
    """
    Returned immediately (202) from POST /documents/upload. The document
    itself does not exist yet — only a queued job does. The frontend must
    poll GET /ingestion-jobs/{job_id} (or /documents/{document_id}) to learn
    the actual outcome; this response is a receipt, not a confirmation.
    """
    success: bool = True
    job_id: str = Field(..., examples=["JOB_A1B2C3D4E5"])
    status: str = "queued"
    original_filename: str
    message: str = "Upload accepted. Processing started in the background."


class IngestionJobOut(BaseModel):
    job_id: str
    document_id: Optional[str] = None
    original_filename: str
    status: str
    current_stage: Optional[str] = None
    stage_log: List[StageLogEntry] = Field(default_factory=list)
    error_message: Optional[str] = None
    action: Optional[str] = None
    retry_of_job_id: Optional[str] = None
    retry_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class IngestionJobListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    jobs: List[IngestionJobOut]


class IngestionJobStatsResponse(BaseModel):
    total_documents: int
    queued: int
    processing: int
    completed: int
    failed: int
    cancelled: int
    failed_ingestion_count: int
    last_ingestion_at: Optional[datetime] = None


class RetryJobResponse(BaseModel):
    success: bool = True
    job_id: str = Field(..., description="The NEW job created for this retry attempt")
    retry_of_job_id: str
    status: str = "queued"
    message: str = "Retry accepted. Processing started in the background."


class CancelJobResponse(BaseModel):
    success: bool
    job_id: str
    status: str
    message: str
