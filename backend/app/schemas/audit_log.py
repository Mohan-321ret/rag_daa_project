"""
Pydantic schemas for the Audit Log API.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


class AuditLogOut(BaseModel):
    id: str
    event_type: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    target_user_id: Optional[str] = None
    target_email: Optional[str] = None
    before_value: Optional[str] = None
    after_value: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", "actor_id", "target_user_id", mode="before")
    @classmethod
    def _stringify_ids(cls, v: object) -> Optional[str]:
        return str(v) if v is not None else None


class AuditLogListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    logs: List[AuditLogOut]
