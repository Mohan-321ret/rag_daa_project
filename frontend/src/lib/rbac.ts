/**
 * Role & Access Matrix — frontend mirror of backend/app/core/permissions.py.
 *
 * This is UX only: it hides/disables controls the caller isn't authorized
 * for so the app doesn't dangle actions that would just 403. The backend
 * enforces every one of these checks independently on every request — this
 * file must never be the only gate on a sensitive action.
 *
 * Keep this in sync with the backend matrix by hand; there is no runtime
 * sharing between the Python and TypeScript codebases here. The backend
 * also serves this same catalog live at GET /api/v1/permissions (gated by
 * PERMISSION_MANAGE) for anything that wants to render it without
 * duplicating it a third time.
 */

export const Role = {
  PLATFORM_OWNER: 'platform_owner',
  SUPER_ADMIN: 'super_admin',
  DOMAIN_MANAGER: 'domain_manager',
  ANALYST: 'analyst',
  STANDARD_EMPLOYEE: 'standard_employee',
  CLIENT_USER: 'client_user',
  GUEST_USER: 'guest_user',
} as const
export type Role = (typeof Role)[keyof typeof Role]

export const Permission = {
  // Platform Management
  PLATFORM_SETTINGS: 'platform:settings',
  SYSTEM_CONFIG: 'platform:system_config',
  SECURITY_SETTINGS: 'platform:security_settings',

  // User Management
  USER_CREATE: 'user:create',
  USER_READ: 'user:read',
  USER_UPDATE: 'user:update',
  USER_DEACTIVATE: 'user:deactivate',
  ROLE_ASSIGN: 'role:assign',
  DOMAIN_ASSIGN: 'domain:assign',
  DOMAIN_MANAGE: 'domain:manage',
  PERMISSION_MANAGE: 'permission:manage',

  // Document Management
  DOCUMENT_UPLOAD: 'document:upload',
  DOCUMENT_READ: 'document:read',
  DOCUMENT_UPDATE: 'document:update',
  DOCUMENT_DELETE: 'document:delete',
  DOCUMENT_VERSION_MANAGE: 'document:version_manage',

  // Data Injection
  INGESTION_MONITOR: 'ingestion:monitor',
  INGESTION_RETRY: 'ingestion:retry',

  // Chunk Management
  CHUNK_VIEW: 'chunk:view',
  CHUNK_REINDEX: 'chunk:reindex',
  CHUNK_DELETE: 'chunk:delete',
  CHUNK_REBUILD_INDEX: 'chunk:rebuild_index',

  // LLM Management
  LLM_VIEW: 'llm:view',
  LLM_CONFIGURE: 'llm:configure',

  // Query Management
  QUERY_LOG_VIEW_OWN: 'query_log:view_own',
  QUERY_LOG_VIEW_DOMAIN: 'query_log:view_domain',
  QUERY_LOG_VIEW_GLOBAL: 'query_log:view_global',
  QUERY_LOG_EXPORT: 'query_log:export',

  // Ticket Management
  TICKET_CREATE: 'ticket:create',
  TICKET_VIEW_OWN: 'ticket:view_own',
  TICKET_VIEW_DOMAIN: 'ticket:view_domain',
  TICKET_ASSIGN: 'ticket:assign',
  TICKET_RESOLVE: 'ticket:resolve',
  TICKET_CLOSE: 'ticket:close',

  // Analytics
  ANALYTICS_VIEW_PERSONAL: 'analytics:view_personal',
  ANALYTICS_VIEW_DOMAIN: 'analytics:view_domain',
  ANALYTICS_VIEW_PLATFORM: 'analytics:view_platform',
} as const
export type Permission = (typeof Permission)[keyof typeof Permission]

export const ROLE_RANK: Record<Role, number> = {
  [Role.GUEST_USER]: 0,
  [Role.CLIENT_USER]: 1,
  [Role.STANDARD_EMPLOYEE]: 2,
  [Role.ANALYST]: 3,
  [Role.DOMAIN_MANAGER]: 4,
  [Role.SUPER_ADMIN]: 5,
  [Role.PLATFORM_OWNER]: 6,
}

const ALL_PERMISSIONS = Object.values(Permission) as Permission[]

export const ROLE_PERMISSIONS: Record<Role, Set<Permission>> = {
  [Role.PLATFORM_OWNER]: new Set(ALL_PERMISSIONS),
  [Role.SUPER_ADMIN]: new Set(ALL_PERMISSIONS),

  [Role.DOMAIN_MANAGER]: new Set([
    // User management is DOMAIN-SCOPED for this role — see the backend's
    // app/services/domain_service.py. Holding these lets a domain manager
    // act on users, but only ones sharing a domain with them.
    Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE, Permission.USER_DEACTIVATE,
    Permission.ROLE_ASSIGN, Permission.DOMAIN_ASSIGN,
    Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
    Permission.DOCUMENT_DELETE, Permission.DOCUMENT_VERSION_MANAGE,
    Permission.INGESTION_MONITOR, Permission.INGESTION_RETRY,
    Permission.CHUNK_VIEW, Permission.CHUNK_REINDEX, Permission.CHUNK_DELETE,
    Permission.CHUNK_REBUILD_INDEX,
    Permission.LLM_VIEW, Permission.LLM_CONFIGURE,
    Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_EXPORT,
    Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
    Permission.TICKET_ASSIGN, Permission.TICKET_RESOLVE, Permission.TICKET_CLOSE,
    Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
  ]),

  [Role.ANALYST]: new Set([
    Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ,
    Permission.CHUNK_VIEW,
    Permission.LLM_VIEW, Permission.LLM_CONFIGURE,
    Permission.QUERY_LOG_VIEW_OWN, Permission.QUERY_LOG_VIEW_DOMAIN, Permission.QUERY_LOG_EXPORT,
    Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN, Permission.TICKET_VIEW_DOMAIN,
    Permission.ANALYTICS_VIEW_PERSONAL, Permission.ANALYTICS_VIEW_DOMAIN,
    Permission.ANALYTICS_VIEW_PLATFORM,
  ]),

  [Role.STANDARD_EMPLOYEE]: new Set([
    Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ,
    Permission.LLM_VIEW, Permission.LLM_CONFIGURE,
    Permission.QUERY_LOG_VIEW_OWN,
    Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN,
    Permission.ANALYTICS_VIEW_PERSONAL,
  ]),

  [Role.CLIENT_USER]: new Set([
    Permission.DOCUMENT_READ,
    Permission.QUERY_LOG_VIEW_OWN,
    Permission.TICKET_CREATE, Permission.TICKET_VIEW_OWN,
  ]),

  [Role.GUEST_USER]: new Set([
    Permission.DOCUMENT_READ,
  ]),
}

function asRole(role: string | null | undefined): Role | null {
  return role && (Object.values(Role) as string[]).includes(role) ? (role as Role) : null
}

export function hasPermission(role: string | null | undefined, permission: Permission): boolean {
  const r = asRole(role)
  return r !== null && ROLE_PERMISSIONS[r].has(permission)
}

export function hasAnyPermission(role: string | null | undefined, permissions: Permission[]): boolean {
  return permissions.some(p => hasPermission(role, p))
}

export function hasAllPermissions(role: string | null | undefined, permissions: Permission[]): boolean {
  return permissions.every(p => hasPermission(role, p))
}

/** A caller may never assign a role ranked above their own (equal is fine). */
export function canAssignRole(assignerRole: string | null | undefined, targetRole: string): boolean {
  const assigner = asRole(assignerRole)
  const target = asRole(targetRole)
  if (assigner === null || target === null) return false
  return ROLE_RANK[target] <= ROLE_RANK[assigner]
}

export const ROLE_LABELS: Record<Role, string> = {
  [Role.PLATFORM_OWNER]: 'Platform Owner',
  [Role.SUPER_ADMIN]: 'Super Admin',
  [Role.DOMAIN_MANAGER]: 'Domain Manager',
  [Role.ANALYST]: 'Analyst',
  [Role.STANDARD_EMPLOYEE]: 'Standard Employee',
  [Role.CLIENT_USER]: 'Client User',
  [Role.GUEST_USER]: 'Guest User',
}
