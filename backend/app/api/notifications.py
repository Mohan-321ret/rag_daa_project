"""
User Notifications API Router
-----------------------------
Provides endpoints for retrieving and managing in-app user notifications.
"""
from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.models.user_notification import UserNotification
from app.schemas.notification import NotificationListResponse, NotificationOut
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["User Notifications"])


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="Get current user's in-app notifications",
)
def get_user_notifications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """Fetch notifications directed to the currently logged in user."""
    query = db.query(UserNotification).filter(UserNotification.user_id == current_user.id)
    total = query.count()
    unread_count = query.filter(UserNotification.read == False).count()  # noqa: E712

    notifs = (
        query.order_by(UserNotification.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return NotificationListResponse(
        total=total,
        unread_count=unread_count,
        notifications=[NotificationOut.model_validate(n) for n in notifs],
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationOut,
    summary="Mark notification as read",
)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """Mark a specific notification as read."""
    notif = (
        db.query(UserNotification)
        .filter(UserNotification.id == notification_id, UserNotification.user_id == current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    notif.read = True
    db.commit()
    db.refresh(notif)
    return NotificationOut.model_validate(notif)


@router.post(
    "/mark-all-read",
    summary="Mark all user's notifications as read",
)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Mark all notifications for the current user as read."""
    updated = (
        db.query(UserNotification)
        .filter(UserNotification.user_id == current_user.id, UserNotification.read == False)  # noqa: E712
        .update({"read": True}, synchronize_session=False)
    )
    db.commit()
    return {"status": "success", "marked_read": updated}
