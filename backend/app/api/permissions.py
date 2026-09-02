"""
Permissions API Router  –  User Management ("manage permissions")
----------------------------------------------------------------------
Endpoint: GET /api/v1/permissions

Read-only introspection of the Role & Access Matrix: the permission catalog
(grouped by the 9 functional categories) and the full role -> permissions
grant matrix. Exists so a future Admin Panel can RENDER the matrix instead
of hardcoding it a second time — the moment this endpoint's response
diverges from what routers actually enforce, something upstream (this
file's imports) is stale, not this file's logic.

This endpoint is deliberately read-only: the matrix is defined in code
(app/core/permissions.py), not editable at runtime. That is a deliberate
security choice, not a missing feature — a permission matrix that can be
rewritten via an API call is a much bigger attack surface than one that
ships with the application and requires a code change (and review) to
alter.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.permissions import (
    PERMISSION_CATALOG,
    PERMISSION_DESCRIPTIONS,
    Permission,
    ROLE_PERMISSIONS,
    ROLE_RANK,
    Role,
)
from app.models.user import User
from app.services.auth_service import require_permission

router = APIRouter(prefix="/permissions", tags=["User & Access Management"])


@router.get("/", summary="View the permission catalog and role matrix")
def get_permission_matrix(
    _: User = Depends(require_permission(Permission.PERMISSION_MANAGE)),
) -> dict:
    return {
        "categories": [
            {
                "key": cat.key,
                "label": cat.label,
                "permissions": [
                    {"key": p.value, "description": PERMISSION_DESCRIPTIONS.get(p, "")}
                    for p in cat.permissions
                ],
            }
            for cat in PERMISSION_CATALOG
        ],
        "roles": [
            {
                "key": role.value,
                "rank": ROLE_RANK[role],
                "permissions": sorted(p.value for p in ROLE_PERMISSIONS.get(role, frozenset())),
            }
            for role in Role
        ],
    }
