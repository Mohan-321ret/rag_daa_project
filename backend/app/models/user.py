"""
User ORM Model  –  Authentication Module
------------------------------------------
Represents the `users` table: registered accounts for the JWT-based
Bearer-token authentication used by the frontend's login/session flow.

`role` drives RBAC (see app/core/permissions.py for the Role enum and the
centralized permission matrix — never branch on this raw string elsewhere).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class User(Base):
    """Maps to the `users` table."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    email = Column(String(255), unique=True, nullable=False, index=True)
    # NULL for accounts created via Google OAuth (no local password).
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # "local" (email+password) or "google" (created via Google Sign-In).
    auth_provider = Column(String(20), nullable=False, default="local", server_default="local")
    picture = Column(String(512), nullable=True)

    # RBAC role — one of app.core.permissions.Role. Defaults to the least-
    # privileged role for self-registered accounts (see app/api/auth.py for
    # the bootstrap exception: the very first user ever created becomes
    # PLATFORM_OWNER so there's always someone able to promote others).
    role = Column(String(32), nullable=False, default="guest_user", server_default="guest_user")

    # Free-text organizational label — distinct from `domain` (the managed,
    # access-control-relevant entity; see app/models/domain.py and
    # UserDomain). department is purely descriptive, mirrors Document.department.
    department = Column(String(256), nullable=True)

    last_login = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    requested_tickets = relationship(
        "Ticket", back_populates="user", foreign_keys="Ticket.user_id"
    )
    managed_tickets = relationship(
        "Ticket", back_populates="assigned_manager", foreign_keys="Ticket.assigned_manager_id"
    )

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"
