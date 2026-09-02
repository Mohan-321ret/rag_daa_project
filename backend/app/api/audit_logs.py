"""
Audit Logs API Router  –  User, Domain & Access Management
------------------------------------------------------------
Endpoint: GET /api/v1/audit-logs/  (Permission.SECURITY_SETTINGS)

Read-only view of the audit trail written by app/services/audit_service.py.
Gated by SECURITY_SETTINGS (Phase 2's Role & Access Matrix defined this
permission with zero enforcement points at the time — "reviewing who changed
what" is exactly the security-oversight capability it was meant for, so this
is its first real use, not a new permission).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db.database import get_db
from app.models.audit_log import AUDIT_EVENT_TYPES, AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogListResponse, AuditLogOut
from app.services.auth_service import require_permission

router = APIRouter(prefix="/audit-logs", tags=["Audit Log"])


@router.get("/", response_model=AuditLogListResponse, summary="View the audit trail")
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.SECURITY_SETTINGS)),
    event_type: Optional[str] = Query(default=None, description=f"Filter: one of {AUDIT_EVENT_TYPES}"),
    target_user_id: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditLogListResponse:
    q = db.query(AuditLog)
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if target_user_id:
        q = q.filter(AuditLog.target_user_id == target_user_id)

    total = q.count()
    rows = q.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return AuditLogListResponse(
        total=total, skip=skip, limit=limit,
        logs=[AuditLogOut.model_validate(r) for r in rows],
    )
