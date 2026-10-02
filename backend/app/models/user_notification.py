"""
User Notification ORM Model
---------------------------
Represents notifications sent to users (e.g. ticket resolution, in-app alerts).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class UserNotification(Base):
    """Maps to the `user_notifications` table."""

    __tablename__ = "user_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(32), nullable=False, default="info")  # success, info, warning, error
    action_type = Column(String(64), nullable=True)  # e.g. ticket_resolved
    action_data = Column(Text, nullable=True)  # JSON-encoded payload: {ticket_id, original_query, resolution}
    read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )

    user = relationship("User", backref="notifications")
