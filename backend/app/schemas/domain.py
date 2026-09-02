"""
Pydantic schemas for the Domain Management API.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


class DomainRef(BaseModel):
    """Lightweight domain reference embedded in UserOut — id/key/name only."""
    id: str
    key: str
    name: str

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v: object) -> str:
        return str(v)


class DomainOut(BaseModel):
    id: str
    key: str
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v: object) -> str:
        return str(v)


class DomainListResponse(BaseModel):
    total: int
    domains: List[DomainOut]


class DomainCreateRequest(BaseModel):
    key: str = Field(..., description="URL-safe slug, e.g. 'hr', 'customer-support'.")
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        v = v.strip().lower()
        if not _KEY_PATTERN.match(v):
            raise ValueError(
                "key must be 3-64 lowercase letters/digits/hyphens/underscores, "
                "starting and ending with a letter or digit."
            )
        return v


class DomainUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    is_active: Optional[bool] = None
