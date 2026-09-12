'use client'
/**
 * PermissionGate — renders children only if the current user holds the
 * required permission. Shows a graceful fallback otherwise.
 *
 * Usage:
 *   <PermissionGate permission={Permission.USER_READ}>
 *     <AdminUsersPanel />
 *   </PermissionGate>
 *
 *   <PermissionGate permission={[Permission.TICKET_ASSIGN, Permission.TICKET_RESOLVE]} any>
 *     <TicketActionBar />
 *   </PermissionGate>
 */
import { ShieldOff } from 'lucide-react'
import { usePermission } from '@/lib/usePermission'
import { type Permission } from '@/lib/rbac'

interface PermissionGateProps {
  permission: Permission | Permission[]
  any?: boolean          // if true, pass if user has ANY of the listed permissions
  fallback?: React.ReactNode
  children: React.ReactNode
}

export function PermissionGate({ permission, any: anyMode, fallback, children }: PermissionGateProps) {
  const granted = usePermission(permission, { any: anyMode })
  if (granted) return <>{children}</>
  if (fallback !== undefined) return <>{fallback}</>
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-4 text-center">
      <div className="w-14 h-14 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
        <ShieldOff className="w-6 h-6 text-red-500 dark:text-red-400" />
      </div>
      <div>
        <p className="text-sm font-semibold text-gray-800 dark:text-white/80">Access Restricted</p>
        <p className="text-xs text-gray-500 dark:text-white/40 mt-1 max-w-xs">
          You don&apos;t have permission to view this section. Contact your administrator if you believe this is an error.
        </p>
      </div>
    </div>
  )
}
