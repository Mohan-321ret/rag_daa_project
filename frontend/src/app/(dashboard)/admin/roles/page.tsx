'use client'
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, ChevronRight, Users, KeyRound, Loader2, Shield } from 'lucide-react'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission, ROLE_PERMISSIONS, ROLE_LABELS, Role } from '@/lib/rbac'
import { permissionsApi, type PermissionMatrixResponse } from '@/lib/api'

// Role color mapping
const ROLE_COLORS: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  platform_owner: { bg: 'bg-violet-500/10', text: 'text-violet-300', border: 'border-violet-500/20', dot: 'bg-violet-400' },
  super_admin:    { bg: 'bg-blue-500/10',   text: 'text-blue-300',   border: 'border-blue-500/20',   dot: 'bg-blue-400' },
  domain_manager: { bg: 'bg-cyan-500/10',   text: 'text-cyan-300',   border: 'border-cyan-500/20',   dot: 'bg-cyan-400' },
  analyst:        { bg: 'bg-emerald-500/10', text: 'text-emerald-300', border: 'border-emerald-500/20', dot: 'bg-emerald-400' },
  standard_employee: { bg: 'bg-white/[0.06]', text: 'text-white/60', border: 'border-white/10', dot: 'bg-white/40' },
  client_user:    { bg: 'bg-amber-500/10',  text: 'text-amber-300',  border: 'border-amber-500/20',  dot: 'bg-amber-400' },
  guest_user:     { bg: 'bg-gray-500/10',   text: 'text-gray-400',   border: 'border-gray-500/20',   dot: 'bg-gray-400' },
}

const ROLE_ORDER = ['platform_owner', 'super_admin', 'domain_manager', 'analyst', 'standard_employee', 'client_user', 'guest_user']

// Group permissions by category
const PERMISSION_CATEGORIES = [
  { label: 'Platform', perms: ['platform:settings', 'platform:system_config', 'platform:security_settings'] },
  { label: 'Users',    perms: ['user:create', 'user:read', 'user:update', 'user:deactivate', 'role:assign', 'domain:assign', 'domain:manage', 'permission:manage'] },
  { label: 'Documents', perms: ['document:upload', 'document:read', 'document:update', 'document:delete', 'document:version_manage'] },
  { label: 'Ingestion', perms: ['ingestion:monitor', 'ingestion:retry'] },
  { label: 'Chunks',   perms: ['chunk:view', 'chunk:reindex', 'chunk:delete', 'chunk:rebuild_index'] },
  { label: 'LLM',      perms: ['llm:view', 'llm:configure'] },
  { label: 'Queries',  perms: ['query_log:view_own', 'query_log:view_domain', 'query_log:view_global', 'query_log:export'] },
  { label: 'Tickets',  perms: ['ticket:create', 'ticket:view_own', 'ticket:view_domain', 'ticket:assign', 'ticket:resolve', 'ticket:close'] },
  { label: 'Analytics', perms: ['analytics:view_personal', 'analytics:view_domain', 'analytics:view_platform'] },
]

const PERM_LABEL: Record<string, string> = {
  'platform:settings': 'Platform Settings', 'platform:system_config': 'System Config', 'platform:security_settings': 'Security Settings',
  'user:create': 'Create Users', 'user:read': 'View Users', 'user:update': 'Update Users', 'user:deactivate': 'Deactivate Users',
  'role:assign': 'Assign Roles', 'domain:assign': 'Assign Domains', 'domain:manage': 'Manage Domains', 'permission:manage': 'View Permissions',
  'document:upload': 'Upload Documents', 'document:read': 'Read Documents', 'document:update': 'Update Documents',
  'document:delete': 'Delete Documents', 'document:version_manage': 'Version Manage',
  'ingestion:monitor': 'Monitor Ingestion', 'ingestion:retry': 'Retry Ingestion',
  'chunk:view': 'View Chunks', 'chunk:reindex': 'Re-index Chunks', 'chunk:delete': 'Delete Chunks', 'chunk:rebuild_index': 'Rebuild Index',
  'llm:view': 'View LLMs', 'llm:configure': 'Configure LLM',
  'query_log:view_own': 'View Own Queries', 'query_log:view_domain': 'View Domain Queries', 'query_log:view_global': 'View All Queries', 'query_log:export': 'Export Queries',
  'ticket:create': 'Create Tickets', 'ticket:view_own': 'View Own Tickets', 'ticket:view_domain': 'View Domain Tickets',
  'ticket:assign': 'Assign Tickets', 'ticket:resolve': 'Resolve Tickets', 'ticket:close': 'Close Tickets',
  'analytics:view_personal': 'Personal Analytics', 'analytics:view_domain': 'Domain Analytics', 'analytics:view_platform': 'Platform Analytics',
}

function hasRolePermission(role: string, perm: string): boolean {
  const permissions = ROLE_PERMISSIONS[role as Role]
  return permissions ? permissions.has(perm as Permission) : false
}

export default function RolesPage() {
  const [selected, setSelected] = useState<string>(ROLE_ORDER[0])
  const [livePerms, setLivePerms] = useState<PermissionMatrixResponse | null>(null)

  // Try to load live permission catalog from backend (optional)
  useEffect(() => {
    permissionsApi.matrix().then(setLivePerms).catch(() => {})
  }, [])

  const selectedPerms = ROLE_PERMISSIONS[selected as Role]
  const permCount = selectedPerms?.size ?? 0

  return (
    <PermissionGate permission={Permission.ROLE_ASSIGN}>
      <AdminSectionShell
        title="Roles & Permissions Matrix"
        description="Browse every role and the permissions it grants. Changes require backend configuration."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Roles' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-blue-500/15 text-blue-300 border border-blue-500/20">{ROLE_ORDER.length} roles</span>}
      >
        <div className="flex gap-5">
          {/* Role list */}
          <div className="w-52 flex-shrink-0 space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/30 px-1 mb-3">Select Role</p>
            {ROLE_ORDER.map(role => {
              const c = ROLE_COLORS[role]
              const cnt = ROLE_PERMISSIONS[role as Role]?.size ?? 0
              return (
                <button
                  key={role}
                  onClick={() => setSelected(role)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-all border ${
                    selected === role
                      ? `${c.bg} ${c.text} ${c.border}`
                      : 'text-white/50 border-transparent hover:bg-white/[0.04] hover:text-white/70'
                  }`}
                >
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${c.dot}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate">{ROLE_LABELS[role as Role] ?? role}</p>
                    <p className="text-[10px] opacity-60">{cnt} permissions</p>
                  </div>
                  {selected === role && <ChevronRight className="w-3 h-3 flex-shrink-0" />}
                </button>
              )
            })}
          </div>

          {/* Permission matrix for selected role */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-5">
              <div className={`px-3 py-1.5 rounded-xl border text-sm font-semibold ${ROLE_COLORS[selected]?.bg} ${ROLE_COLORS[selected]?.text} ${ROLE_COLORS[selected]?.border}`}>
                {ROLE_LABELS[selected as Role] ?? selected}
              </div>
              <span className="text-xs text-white/35">{permCount} permissions granted</span>
            </div>

            <div className="space-y-4">
              {PERMISSION_CATEGORIES.map(cat => {
                const granted = cat.perms.filter(p => hasRolePermission(selected, p))
                if (granted.length === 0 && cat.perms.length > 0 && permCount === 0) return null
                return (
                  <motion.div
                    key={cat.label}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4"
                  >
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-xs font-semibold text-white/70">{cat.label}</p>
                      <span className="text-[10px] text-white/30">{granted.length}/{cat.perms.length}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {cat.perms.map(perm => {
                        const has = hasRolePermission(selected, perm)
                        return (
                          <div
                            key={perm}
                            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[11px] transition-all ${
                              has
                                ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/15'
                                : 'bg-white/[0.02] text-white/25 border border-white/[0.05]'
                            }`}
                          >
                            <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${has ? 'bg-emerald-400' : 'bg-white/15'}`} />
                            {PERM_LABEL[perm] ?? perm}
                          </div>
                        )
                      })}
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </div>
        </div>
      </AdminSectionShell>
    </PermissionGate>
  )
}
