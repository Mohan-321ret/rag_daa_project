"""
RBAC Core  –  Role & Access Matrix
------------------------------------------------------
Centralized, framework-agnostic authorization model shared by every API
router. This module defines WHAT the roles and permissions are and HOW they
relate; app/services/auth_service.py defines the FastAPI dependencies that
ENFORCE them (require_role / require_permission) so no router ever hardcodes
"if current_user.role == ...".

Structure:
  - Role            - the 7 platform roles, ranked (ROLE_RANK)
  - Permission       - every fine-grained action in the system, namespaced
                       "resource:action" and grouped into PERMISSION_CATALOG
  - PERMISSION_CATALOG - the matrix organized by the 9 functional categories
                       (Platform Management, User Management, Document
                       Management, Data Injection, Chunk Management, LLM
                       Management, Query Management, Ticket Management,
                       Analytics) — this is what a future Admin Panel /
                       permissions-explorer renders, and what
                       GET /api/v1/permissions serves (see app/api/permissions.py)
  - ROLE_PERMISSIONS - role -> the set of permissions it holds (the actual
                       enforcement matrix; PERMISSION_CATALOG is metadata
                       *about* permissions, this is what routers check)

Extensibility: adding a new permission is a two-line change — one
`Permission` member, one entry in the right PERMISSION_CATALOG category, and
an entry in each role's set in ROLE_PERMISSIONS that should hold it. No
authorization *logic* (require_permission, role_has_permission, the
introspection endpoint) ever needs to change. Several permissions below
(marked "not yet enforced") have zero endpoints wired to them today — they
exist purely to prove that: the catalog and matrix are complete even where
the underlying feature isn't built yet.

A recurring caveat, called out per-permission below: several "domain-scoped"
permissions (TICKET_VIEW_DOMAIN, QUERY_LOG_VIEW_DOMAIN,
ANALYTICS_VIEW_DOMAIN) exist because the role taxonomy names domains
explicitly ("Domain Manager... within assigned domains"), but Ticket/
QueryLog/analytics data isn't linked to a Domain yet (only Document.department
exists, a free-text label with no access-control meaning) — so those three
still behave identically to a global/platform-wide scope. This is documented
instead of hidden so nobody mistakes it for real per-domain isolation.

Domains themselves ARE real (see app/models/domain.py, app/models/user_domain.py)
and User Management IS domain-scoped for real: a DOMAIN_MANAGER's USER_READ/
USER_UPDATE/USER_DEACTIVATE/ROLE_ASSIGN/DOMAIN_ASSIGN only reach users who
share at least one domain with them — see app/services/domain_service.py's
`assert_domain_access` and app/api/users.py, which is the one place in this
codebase domain scoping is fully wired end-to-end today.

Role hierarchy (ROLE_RANK) exists ONLY to police privilege escalation on
role-assignment (see can_assign_role): a caller may never assign a role
ranked above their own. It is not consulted for ordinary permission checks —
those go through ROLE_PERMISSIONS exclusively, so a "higher" role never
silently inherits things it isn't explicitly granted.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List


class Role(str, Enum):
    PLATFORM_OWNER = "platform_owner"
    SUPER_ADMIN = "super_admin"
    DOMAIN_MANAGER = "domain_manager"
    HR = "hr"
    ANALYST = "analyst"
    STANDARD_EMPLOYEE = "standard_employee"
    CLIENT_USER = "client_user"
    GUEST_USER = "guest_user"


class Permission(str, Enum):
    # ── Platform Management ─────────────────────────────────────────────────
    PLATFORM_SETTINGS = "platform:settings"          # not yet enforced — no settings API exists
    SYSTEM_CONFIG = "platform:system_config"          # not yet enforced — no config API exists
    SECURITY_SETTINGS = "platform:security_settings"  # not yet enforced — no security-config API exists

    # ── User Management ──────────────────────────────────────────────────────
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DEACTIVATE = "user:deactivate"
    ROLE_ASSIGN = "role:assign"
    DOMAIN_ASSIGN = "domain:assign"        # assign a USER to domain(s) — distinct from DOMAIN_MANAGE below
    DOMAIN_MANAGE = "domain:manage"        # create/edit/deactivate the domain ENTITIES themselves
    PERMISSION_MANAGE = "permission:manage"  # GET /api/v1/permissions (this catalog, read-only)

    # ── Document Management ──────────────────────────────────────────────────
    DOCUMENT_UPLOAD = "document:upload"            # also covers Data Injection's "initiate ingestion"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPDATE = "document:update"             # not yet enforced — no document-edit endpoint exists
    DOCUMENT_DELETE = "document:delete"             # not yet enforced; also covers "remove documents"
    DOCUMENT_VERSION_MANAGE = "document:version_manage"

    # ── Data Injection ────────────────────────────────────────────────────────
    INGESTION_MONITOR = "ingestion:monitor"
    INGESTION_RETRY = "ingestion:retry"    # also gates POST /ingestion-jobs/{job_id}/cancel

    # ── Chunk Management ──────────────────────────────────────────────────────
    CHUNK_VIEW = "chunk:view"              # also covers "inspect embedding status" (chunk detail includes it)
    CHUNK_REINDEX = "chunk:reindex"
    CHUNK_DELETE = "chunk:delete"          # not yet enforced — no standalone chunk-delete endpoint exists
    CHUNK_REBUILD_INDEX = "chunk:rebuild_index"  # not yet enforced — no full-FAISS-rebuild endpoint exists

    # ── LLM Management ────────────────────────────────────────────────────────
    LLM_VIEW = "llm:view"
    LLM_CONFIGURE = "llm:configure"  # select active/change model/change provider/configure settings —
    # one permission, four facets of the same "administer platform LLM config" capability; not yet
    # enforced anywhere (the per-query `model` override on POST /rag/query is a caller's own request
    # scope, not a platform admin action, so it is intentionally gated by DOCUMENT_READ, not this).

    # ── Query Management ──────────────────────────────────────────────────────
    QUERY_LOG_VIEW_OWN = "query_log:view_own"
    QUERY_LOG_VIEW_DOMAIN = "query_log:view_domain"   # see module docstring: currently global-equivalent
    QUERY_LOG_VIEW_GLOBAL = "query_log:view_global"
    QUERY_LOG_EXPORT = "query_log:export"

    # ── Ticket Management ─────────────────────────────────────────────────────
    TICKET_CREATE = "ticket:create"        # not yet enforced — tickets are raised automatically by the
    # RAG pipeline (see app/services/ticket_service.py), there is no manual "file a ticket" endpoint yet.
    TICKET_VIEW_OWN = "ticket:view_own"
    TICKET_VIEW_DOMAIN = "ticket:view_domain"   # see module docstring: currently global-equivalent
    TICKET_ASSIGN = "ticket:assign"
    TICKET_RESOLVE = "ticket:resolve"
    TICKET_CLOSE = "ticket:close"

    # ── Analytics ─────────────────────────────────────────────────────────────
    ANALYTICS_VIEW_PERSONAL = "analytics:view_personal"  # not yet enforced — no personal-metrics endpoint
    # exists (metrics_service.py only ever aggregates platform-wide); own query history is covered by
    # QUERY_LOG_VIEW_OWN instead.
    ANALYTICS_VIEW_DOMAIN = "analytics:view_domain"      # not yet enforced, same reason as above
    ANALYTICS_VIEW_PLATFORM = "analytics:view_platform"


# ── Role hierarchy (privilege-escalation guard only — see module docstring) ───
ROLE_RANK: Dict[Role, int] = {
    Role.GUEST_USER: 0,
    Role.CLIENT_USER: 1,
    Role.STANDARD_EMPLOYEE: 2,
    Role.ANALYST: 3,
    Role.HR: 3,
    Role.DOMAIN_MANAGER: 4,
    Role.SUPER_ADMIN: 5,
    Role.PLATFORM_OWNER: 6,
}

DEFAULT_ROLE = Role.GUEST_USER  # least privilege for self-registered accounts


@dataclass(frozen=True)
class PermissionCategory:
    key: str
    label: str
    permissions: List[Permission]


# ── Permission catalog: the matrix organized by functional category ───────────
# This is metadata ABOUT permissions (grouping + human labels) for
# introspection/UI — the actual role -> permission grants live in
# ROLE_PERMISSIONS below. Every Permission member appears in exactly one
# category here; app/api/permissions.py asserts that at import time.
PERMISSION_CATALOG: List[PermissionCategory] = [
    PermissionCategory("platform_management", "Platform Management", [
        Permission.PLATFORM_SETTINGS, Permission.SYSTEM_CONFIG, Permission.SECURITY_SETTINGS,
    ]),
    PermissionCategory("user_management", "User Management", [
        Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE,
        Permission.USER_DEACTIVATE, Permission.ROLE_ASSIGN, Permission.DOMAIN_ASSIGN,
        Permission.DOMAIN_MANAGE, Permission.PERMISSION_MANAGE,
    ]),
    PermissionCategory("document_management", "Document Management", [
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE, Permission.DOCUMENT_VERSION_MANAGE,
    ]),
    PermissionCategory("data_injection", "Data Injection", [
        Permission.DOCUMENT_UPLOAD, Permission.INGESTION_MONITOR, Permission.INGESTION_RETRY,
        Permission.DOCUMENT_DELETE,
    ]),
    PermissionCategory("chunk_management", "Chunk Management", [
        Permission.CHUNK_VIEW, Permission.CHUNK_REINDEX, Permission.CHUNK_DELETE,
        Permission.CHUNK_REBUILD_INDEX,
    ]),
    PermissionCategory("llm_management", "LLM Management", [
        Permission.LLM_VIEW, Permission.LLM_CONFIGURE,
    ]),
    PermissionCategory("query_management", "Query Management", [
        Permission.DOCUMENT_READ, Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN,
        Permission.QUERY_LOG_VIEW_GLOBAL, Permission.QUERY_LOG_EXPORT,
    ]),
    PermissionCategory("ticket_management", "Ticket Management", [
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
        Permission.TICKET_ASSIGN, Permission.TICKET_RESOLVE, Permission.TICKET_CLOSE,
    ]),
    PermissionCategory("analytics", "Analytics", [
        Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
        Permission.ANALYTICS_VIEW_PLATFORM,
    ]),
]

# Human-readable description per permission, keyed for the introspection API.
# (Document Management's DOCUMENT_UPLOAD/DOCUMENT_DELETE double as Data
# Injection's "initiate ingestion"/"remove documents" — same permission,
# two category listings above, one description each context.)
PERMISSION_DESCRIPTIONS: Dict[Permission, str] = {
    Permission.PLATFORM_SETTINGS: "View/update platform-wide settings.",
    Permission.SYSTEM_CONFIG: "View/update system configuration.",
    Permission.SECURITY_SETTINGS: "View/update security settings.",
    Permission.USER_CREATE: "Create user accounts.",
    Permission.USER_READ: "View user accounts.",
    Permission.USER_UPDATE: "Update a user's profile fields.",
    Permission.USER_DEACTIVATE: "Deactivate or reactivate a user account.",
    Permission.ROLE_ASSIGN: "Assign a role to a user (bounded by rank — see can_assign_role).",
    Permission.DOMAIN_ASSIGN: "Assign a user to one or more domains.",
    Permission.DOMAIN_MANAGE: "Create, rename, describe, or deactivate a domain.",
    Permission.PERMISSION_MANAGE: "View the permission catalog and role matrix.",
    Permission.DOCUMENT_UPLOAD: "Upload a document / initiate ingestion.",
    Permission.DOCUMENT_READ: "View a document / query the platform.",
    Permission.DOCUMENT_UPDATE: "Edit a document's metadata or content.",
    Permission.DOCUMENT_DELETE: "Delete / remove a document.",
    Permission.DOCUMENT_VERSION_MANAGE: "View and compare a document's version history.",
    Permission.INGESTION_MONITOR: "Monitor ingestion events and the folder watcher.",
    Permission.INGESTION_RETRY: "Retry a failed ingestion.",
    Permission.CHUNK_VIEW: "View chunks and their embedding/index status.",
    Permission.CHUNK_REINDEX: "Re-index chunks (e.g. start/stop the folder watcher).",
    Permission.CHUNK_DELETE: "Delete individual chunks.",
    Permission.CHUNK_REBUILD_INDEX: "Rebuild the full vector index.",
    Permission.LLM_VIEW: "View configured LLMs and their availability.",
    Permission.LLM_CONFIGURE: "Select the active LLM, change model/provider, configure model settings.",
    Permission.QUERY_LOG_VIEW_OWN: "View your own query history.",
    Permission.QUERY_LOG_VIEW_DOMAIN: "View query history for your domain.",
    Permission.QUERY_LOG_VIEW_GLOBAL: "View query history platform-wide.",
    Permission.QUERY_LOG_EXPORT: "Export query logs.",
    Permission.TICKET_CREATE: "Manually create a review ticket.",
    Permission.TICKET_VIEW_OWN: "View tickets you raised.",
    Permission.TICKET_VIEW_DOMAIN: "View all tickets in your domain.",
    Permission.TICKET_ASSIGN: "Claim/reassign a ticket.",
    Permission.TICKET_RESOLVE: "Resolve a ticket.",
    Permission.TICKET_CLOSE: "Close (dismiss) a ticket without resolving it.",
    Permission.ANALYTICS_VIEW_PERSONAL: "View your own usage analytics.",
    Permission.ANALYTICS_VIEW_DOMAIN: "View domain-wide analytics.",
    Permission.ANALYTICS_VIEW_PLATFORM: "View platform-wide analytics.",
}


# ── Centralized permission matrix ──────────────────────────────────────────────
# The single source of truth: every router checks against THIS, never against
# `current_user.role` directly.
ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.PLATFORM_OWNER: frozenset(Permission),  # every permission that exists

    Role.SUPER_ADMIN: frozenset(Permission),  # full permission set too — the
    # ceiling between SUPER_ADMIN and PLATFORM_OWNER is enforced by ROLE_RANK
    # in can_assign_role (a SUPER_ADMIN can never grant PLATFORM_OWNER), not
    # by withholding permissions here.

    Role.DOMAIN_MANAGER: frozenset({
        # User management is DOMAIN-SCOPED for this role (see module docstring
        # + app/services/domain_service.py) — holding these permissions lets a
        # domain manager act on users, but only ones sharing a domain with
        # them. DOMAIN_MANAGE (creating the domain entities themselves) is
        # deliberately withheld — that stays an exec-tier ("Administrators")
        # action per the spec, distinct from assigning existing domains to
        # users within one's own scope.
        Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE, Permission.USER_DEACTIVATE,
        Permission.ROLE_ASSIGN, Permission.DOMAIN_ASSIGN,
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE, Permission.DOCUMENT_VERSION_MANAGE,
        Permission.INGESTION_MONITOR, Permission.INGESTION_RETRY,
        Permission.CHUNK_VIEW, Permission.CHUNK_REINDEX, Permission.CHUNK_DELETE,
        Permission.CHUNK_REBUILD_INDEX,
        Permission.LLM_VIEW,
        Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_EXPORT,
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
        Permission.TICKET_ASSIGN, Permission.TICKET_RESOLVE, Permission.TICKET_CLOSE,
        Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
    }),

    Role.HR: frozenset({
        Permission.USER_READ, Permission.USER_UPDATE,
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE, Permission.DOCUMENT_VERSION_MANAGE,
        Permission.INGESTION_MONITOR, Permission.INGESTION_RETRY,
        Permission.CHUNK_VIEW,
        Permission.LLM_VIEW,
        Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_EXPORT,
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
        Permission.TICKET_ASSIGN, Permission.TICKET_RESOLVE, Permission.TICKET_CLOSE,
        Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
    }),

    Role.ANALYST: frozenset({
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ,
        Permission.CHUNK_VIEW,
        Permission.LLM_VIEW,
        Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_EXPORT,
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
        Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
        Permission.ANALYTICS_VIEW_PLATFORM,
    }),

    Role.STANDARD_EMPLOYEE: frozenset({
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ,
        Permission.LLM_VIEW,
        Permission.QUERY_LOG_VIEW_OWN,
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN,
        Permission.ANALYTICS_VIEW_PERSONAL,
    }),

    Role.CLIENT_USER: frozenset({
        Permission.DOCUMENT_READ,
        Permission.QUERY_LOG_VIEW_OWN,
        Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN,
    }),

    Role.GUEST_USER: frozenset({
        Permission.DOCUMENT_READ,
    }),
}


def role_has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def role_has_any_permission(role: Role, permissions: tuple[Permission, ...]) -> bool:
    return any(role_has_permission(role, p) for p in permissions)


def role_has_all_permissions(role: Role, permissions: tuple[Permission, ...]) -> bool:
    return all(role_has_permission(role, p) for p in permissions)


def can_assign_role(assigner_role: Role, target_role: Role) -> bool:
    """
    A role can never assign a role ranked ABOVE its own (assigning an EQUAL
    rank, e.g. one PLATFORM_OWNER promoting another user to PLATFORM_OWNER,
    is allowed). Callers must also independently hold Permission.ROLE_ASSIGN
    — this only answers "is the target rank within reach", not "is this
    caller allowed to assign roles at all".
    """
    return ROLE_RANK[target_role] <= ROLE_RANK[assigner_role]
