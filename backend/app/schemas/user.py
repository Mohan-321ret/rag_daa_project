"""
Pydantic schemas for the User & Access Management API.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.permissions import Role
from app.schemas.auth import UserOut


class UserListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    users: List[UserOut]


def _validate_role(v: Optional[str]) -> Optional[str]:
    if v is not None:
        try:
            Role(v)
        except ValueError:
            valid = ", ".join(r.value for r in Role)
            raise ValueError(f"role must be one of: {valid}")
    return v


class UserCreateRequest(BaseModel):
    """
    Admin-initiated account creation (Permission.USER_CREATE) — distinct
    from self-serve POST /auth/register: the admin sets the role/domain(s)/
    department up front instead of the account starting at GUEST_USER with
    no domain. The admin sets an initial password directly (there is no
    email/invite infrastructure in this project); the new user can change
    it later the same way any account would.
    """
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)
    department: Optional[str] = Field(default=None, max_length=256)
    role: str = Field(default="guest_user")
    domain_ids: List[str] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        return _validate_role(v)


class UserUpdateRequest(BaseModel):
    """
    Partial update. Each field is authorized independently in
    app/api/users.py against a different permission (full_name/department ->
    USER_UPDATE, is_active -> USER_DEACTIVATE, role -> ROLE_ASSIGN,
    domain_ids -> DOMAIN_ASSIGN) so a caller holding only one of those
    permissions can still use this schema for the field(s) they're allowed
    to touch.
    """
    full_name: Optional[str] = Field(default=None, max_length=255)
    department: Optional[str] = Field(default=None, max_length=256)
    is_active: Optional[bool] = None
    role: Optional[str] = None
    domain_ids: Optional[List[str]] = None   # replaces the full membership set; [0] becomes primary

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: Optional[str]) -> Optional[str]:
        return _validate_role(v)
