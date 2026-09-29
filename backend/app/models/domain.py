"""
Domain ORM Model  –  User, Domain & Access Management
------------------------------------------------------
Represents the `domains` table: organizational units (HR, Finance, IT, ...)
used to scope Domain Manager authority and, eventually, document/retrieval
visibility (not yet — see app/core/permissions.py's module docstring).

Domains are NOT hardcoded — this table is fully admin-managed
(POST/PATCH /api/v1/domains, gated by Permission.DOMAIN_MANAGE). The
db/base.py migration seeds a starter set (HR, Finance, IT, Operations,
Legal, Sales, Engineering) as ordinary rows, not as a fixed enum — deleting/
renaming/adding beyond that set works identically for every domain.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class Domain(Base):
    """Maps to the `domains` table."""

    __tablename__ = "domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # URL/API-friendly slug, e.g. "hr", "finance" — stable identifier even if
    # `name` is later renamed for display.
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

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

    routed_tickets = relationship(
        "Ticket", back_populates="routed_domain", foreign_keys="Ticket.routed_domain_id"
    )

    def __repr__(self) -> str:
        return f"<Domain {self.key!r} ({self.name!r})>"
