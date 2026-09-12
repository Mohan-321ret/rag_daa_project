'use client'
import { Lock, Check, X } from 'lucide-react'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission, ROLE_PERMISSIONS, ROLE_LABELS, type Role } from '@/lib/rbac'

const ROLES_IN_ORDER = ['platform_owner', 'super_admin', 'domain_manager', 'hr', 'analyst', 'standard_employee', 'client_user', 'guest_user']

const POLICY_SECTIONS = [
  {
    label: 'Platform Admin', perms: [
      { key: 'platform:settings', label: 'Platform Settings' },
      { key: 'platform:system_config', label: 'System Config' },
      { key: 'platform:security_settings', label: 'Security' },
      { key: 'permission:manage', label: 'Permissions' },
      { key: 'domain:manage', label: 'Manage Domains' },
    ],
  },
  {
    label: 'User Management', perms: [
      { key: 'user:create', label: 'Create Users' },
      { key: 'user:read', label: 'View Users' },
      { key: 'user:update', label: 'Update Users' },
      { key: 'user:deactivate', label: 'Deactivate' },
      { key: 'role:assign', label: 'Assign Roles' },
      { key: 'domain:assign', label: 'Assign Domains' },
    ],
  },
  {
    label: 'Knowledge & Data', perms: [
      { key: 'document:upload', label: 'Upload Docs' },
      { key: 'document:read', label: 'Read Docs' },
      { key: 'document:delete', label: 'Delete Docs' },
      { key: 'ingestion:monitor', label: 'Monitor Ingestion' },
      { key: 'ingestion:retry', label: 'Retry Ingestion' },
      { key: 'chunk:view', label: 'View Chunks' },
      { key: 'chunk:reindex', label: 'Re-index Chunks' },
    ],
  },
  {
    label: 'LLM & Queries', perms: [
      { key: 'llm:view', label: 'View LLMs' },
      { key: 'llm:configure', label: 'Configure LLM' },
      { key: 'query_log:view_own', label: 'Own Queries' },
      { key: 'query_log:view_domain', label: 'Domain Queries' },
      { key: 'query_log:view_global', label: 'All Queries' },
      { key: 'query_log:export', label: 'Export Queries' },
    ],
  },
  {
    label: 'Tickets & Analytics', perms: [
      { key: 'ticket:create', label: 'Create Tickets' },
      { key: 'ticket:view_own', label: 'Own Tickets' },
      { key: 'ticket:view_domain', label: 'Domain Tickets' },
      { key: 'ticket:assign', label: 'Assign Tickets' },
      { key: 'ticket:resolve', label: 'Resolve Tickets' },
      { key: 'analytics:view_personal', label: 'Personal Analytics' },
      { key: 'analytics:view_domain', label: 'Domain Analytics' },
      { key: 'analytics:view_platform', label: 'Platform Analytics' },
    ],
  },
]

const ROLE_SHORT: Record<string, string> = {
  platform_owner: 'Owner', super_admin: 'Super', domain_manager: 'Domain Mgr',
  hr: 'HR', analyst: 'Analyst', standard_employee: 'Employee', client_user: 'Client', guest_user: 'Guest',
}

function Cell({ granted }: { granted: boolean }) {
  return (
    <td className="px-2 py-2 text-center">
      {granted
        ? <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 mx-auto" />
        : <X className="w-3.5 h-3.5 text-gray-300 dark:text-white/15 mx-auto" />}
    </td>
  )
}

export default function AccessPoliciesPage() {
  return (
    <PermissionGate permission={Permission.PERMISSION_MANAGE}>
      <AdminSectionShell
        title="Access Policies"
        description="Full permission matrix — what each role can do across the platform."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Access Policies' }]}
      >
        <div className="overflow-x-auto bg-white dark:bg-transparent rounded-xl border border-gray-200 dark:border-white/[0.06] shadow-sm dark:shadow-none p-2">
          <table className="w-full text-xs min-w-[800px]">
            <thead>
              <tr>
                <th className="text-left px-3 py-3 text-gray-500 dark:text-white/35 font-medium w-44">Permission</th>
                {ROLES_IN_ORDER.map(r => (
                  <th key={r} className="px-2 py-3 text-center">
                    <span className="text-gray-700 dark:text-white/50 font-medium whitespace-nowrap">{ROLE_SHORT[r]}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {POLICY_SECTIONS.map(section => (
                <>
                  <tr key={`hdr-${section.label}`}>
                    <td colSpan={ROLES_IN_ORDER.length + 1} className="px-3 py-2 pt-4">
                      <span className="text-[11px] font-semibold text-gray-500 dark:text-white/40 uppercase tracking-wider">{section.label}</span>
                    </td>
                  </tr>
                  {section.perms.map(perm => (
                    <tr key={perm.key} className="border-b border-gray-100 dark:border-white/[0.04] hover:bg-gray-50 dark:hover:bg-white/[0.02] transition-colors">
                      <td className="px-3 py-2 text-gray-800 dark:text-white/60">{perm.label}</td>
                      {ROLES_IN_ORDER.map(role => (
                        <Cell
                          key={role}
                          granted={ROLE_PERMISSIONS[role as Role]?.has(perm.key as Permission) ?? false}
                        />
                      ))}
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex items-center gap-4 text-[11px] text-adaptive-muted">
          <span className="flex items-center gap-1.5"><Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" /> Permission granted</span>
          <span className="flex items-center gap-1.5"><X className="w-3 h-3 text-gray-400 dark:text-white/20" /> Not granted</span>
          <span className="ml-auto">Matrix mirrors backend <code className="text-gray-500 dark:text-white/20">app/core/permissions.py</code></span>
        </div>
      </AdminSectionShell>
    </PermissionGate>
  )
}
