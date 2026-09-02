'use client'
/**
 * Reusable frontend permission helpers (RBAC Foundation).
 *
 * Reads the current user's role from the app store and checks it against
 * the same permission matrix the backend enforces (see lib/rbac.ts). Use
 * these to hide/disable controls for a better UX — the backend is the real
 * gate, this just avoids showing a button that would 403.
 */
import { useAppStore } from '@/store/appStore'
import { hasAllPermissions, hasAnyPermission, hasPermission, type Permission } from '@/lib/rbac'

export function useRole(): string | null {
  return useAppStore(s => s.currentUser?.role ?? null)
}

/** True if the current user's role holds `permission` (or all/any of a list). */
export function usePermission(permission: Permission | Permission[], opts?: { any?: boolean }): boolean {
  const role = useRole()
  if (Array.isArray(permission)) {
    return opts?.any ? hasAnyPermission(role, permission) : hasAllPermissions(role, permission)
  }
  return hasPermission(role, permission)
}
