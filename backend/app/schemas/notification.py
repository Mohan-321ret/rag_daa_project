"""
Notification Pydantic Schemas
-----------------------------
Defines request and response models for in-app user notifications.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    ticket_id: Optional[str] = None
    title: str
    message: str
    type: str = "info"  # success, info, warning, error
    action_type: Optional[str] = None
    action_data: Optional[str] = None
    read: bool = False
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    notifications: List[NotificationOut]
