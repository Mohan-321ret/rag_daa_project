'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useRole } from '@/lib/usePermission'
import { hasPermission, hasAnyPermission, Permission } from '@/lib/rbac'

/**
 * Admin Panel root — redirects to the first section the user has access to.
 * This prevents a blank page when navigating to /admin.
 */
export default function AdminRootPage() {
  const router = useRouter()
  const role = useRole()

  useEffect(() => {
    if (!role) return
    // Priority order: first accessible section
    if (hasPermission(role, Permission.USER_READ)) {
      router.replace('/admin/users')
    } else if (hasPermission(role, Permission.INGESTION_MONITOR)) {
      router.replace('/admin/ingestion')
    } else if (hasPermission(role, Permission.CHUNK_VIEW)) {
      router.replace('/admin/chunk-indexing')
    } else if (hasPermission(role, Permission.LLM_VIEW)) {
      router.replace('/admin/llm')
    } else if (hasAnyPermission(role, [Permission.QUERY_LOG_VIEW_GLOBAL, Permission.QUERY_LOG_VIEW_DOMAIN])) {
      router.replace('/admin/query-logs')
    } else if (hasAnyPermission(role, [Permission.TICKET_VIEW_DOMAIN, Permission.TICKET_ASSIGN])) {
      router.replace('/admin/tickets')
    } else if (hasPermission(role, Permission.ANALYTICS_VIEW_PLATFORM)) {
      router.replace('/admin/analytics')
    } else {
      router.replace('/dashboard')
    }
  }, [role, router])

  return (
    <div className="flex items-center justify-center py-20 text-gray-400 dark:text-white/30 text-sm">
      Redirecting…
    </div>
  )
}
