"""
Pydantic schemas for the Authentication API.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.domain import DomainRef


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class GoogleLoginRequest(BaseModel):
    # The ID token ("credential") returned by Google Identity Services on the
    # frontend. Verified server-side against GOOGLE_CLIENT_ID.
    credential: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    auth_provider: str = "local"
    picture: Optional[str] = None
    role: str = "guest_user"
    is_active: bool = True
    status: str = "active"   # derived from is_active — "active" | "inactive"
    department: Optional[str] = None
    domains: List[DomainRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v: object) -> str:
        # User.id is a UUID column (uuid.UUID at the Python level) — pydantic
        # v2 does not auto-coerce UUID -> str, so convert explicitly here.
        return str(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int   # seconds
    user: UserOut
