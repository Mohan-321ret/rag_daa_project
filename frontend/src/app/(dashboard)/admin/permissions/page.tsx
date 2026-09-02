'use client'
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, Search, ChevronDown } from 'lucide-react'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { permissionsApi } from '@/lib/api'

// Fallback static catalog grouped by category
const STATIC_CATALOG = [
  { category: 'Platform Management', permissions: [
    { key: 'platform:settings', label: 'Platform Settings', description: 'View/update platform-wide settings.' },
    { key: 'platform:system_config', label: 'System Config', description: 'View/update system configuration.' },
    { key: 'platform:security_settings', label: 'Security Settings', description: 'View/update security settings.' },
  ]},
  { category: 'User Management', permissions: [
    { key: 'user:create', label: 'Create Users', description: 'Create user accounts.' },
    { key: 'user:read', label: 'View Users', description: 'View user accounts.' },
    { key: 'user:update', label: 'Update Users', description: 'Update a user\'s profile fields.' },
    { key: 'user:deactivate', label: 'Deactivate Users', description: 'Deactivate or reactivate a user account.' },
    { key: 'role:assign', label: 'Assign Roles', description: 'Assign a role to a user (bounded by rank).' },
    { key: 'domain:assign', label: 'Assign Domains', description: 'Assign a user to one or more domains.' },
    { key: 'domain:manage', label: 'Manage Domains', description: 'Create, rename, describe, or deactivate a domain.' },
    { key: 'permission:manage', label: 'View Permissions', description: 'View the permission catalog and role matrix.' },
  ]},
  { category: 'Document Management', permissions: [
    { key: 'document:upload', label: 'Upload Documents', description: 'Upload a document / initiate ingestion.' },
    { key: 'document:read', label: 'Read Documents', description: 'View a document / query the platform.' },
    { key: 'document:update', label: 'Update Documents', description: 'Edit a document\'s metadata or content.' },
    { key: 'document:delete', label: 'Delete Documents', description: 'Delete / remove a document.' },
    { key: 'document:version_manage', label: 'Version Management', description: 'View and compare a document\'s version history.' },
  ]},
  { category: 'Data Injection', permissions: [
    { key: 'ingestion:monitor', label: 'Monitor Ingestion', description: 'Monitor ingestion events and the folder watcher.' },
    { key: 'ingestion:retry', label: 'Retry Ingestion', description: 'Retry a failed ingestion.' },
  ]},
  { category: 'Chunk Management', permissions: [
    { key: 'chunk:view', label: 'View Chunks', description: 'View chunks and their embedding/index status.' },
    { key: 'chunk:reindex', label: 'Re-index Chunks', description: 'Re-index chunks.' },
    { key: 'chunk:delete', label: 'Delete Chunks', description: 'Delete individual chunks.' },
    { key: 'chunk:rebuild_index', label: 'Rebuild Index', description: 'Rebuild the full vector index.' },
  ]},
  { category: 'LLM Management', permissions: [
    { key: 'llm:view', label: 'View LLMs', description: 'View configured LLMs and their availability.' },
    { key: 'llm:configure', label: 'Configure LLM', description: 'Select active LLM, change model/provider, configure settings.' },
  ]},
  { category: 'Query Management', permissions: [
    { key: 'query_log:view_own', label: 'View Own Queries', description: 'View your own query history.' },
    { key: 'query_log:view_domain', label: 'View Domain Queries', description: 'View query history for your domain.' },
    { key: 'query_log:view_global', label: 'View All Queries', description: 'View query history platform-wide.' },
    { key: 'query_log:export', label: 'Export Queries', description: 'Export query logs.' },
  ]},
  { category: 'Ticket Management', permissions: [
    { key: 'ticket:create', label: 'Create Tickets', description: 'Manually create a review ticket.' },
    { key: 'ticket:view_own', label: 'View Own Tickets', description: 'View tickets you raised.' },
    { key: 'ticket:view_domain', label: 'View Domain Tickets', description: 'View all tickets in your domain.' },
    { key: 'ticket:assign', label: 'Assign Tickets', description: 'Claim/reassign a ticket.' },
    { key: 'ticket:resolve', label: 'Resolve Tickets', description: 'Resolve a ticket.' },
    { key: 'ticket:close', label: 'Close Tickets', description: 'Close (dismiss) a ticket.' },
  ]},
  { category: 'Analytics', permissions: [
    { key: 'analytics:view_personal', label: 'Personal Analytics', description: 'View your own usage analytics.' },
    { key: 'analytics:view_domain', label: 'Domain Analytics', description: 'View domain-wide analytics.' },
    { key: 'analytics:view_platform', label: 'Platform Analytics', description: 'View platform-wide analytics.' },
  ]},
]

const CAT_COLORS: Record<string, string> = {
  'Platform Management': 'text-violet-400 bg-violet-500/10 border-violet-500/20',
  'User Management': 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  'Document Management': 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  'Data Injection': 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  'Chunk Management': 'text-teal-400 bg-teal-500/10 border-teal-500/20',
  'LLM Management': 'text-purple-400 bg-purple-500/10 border-purple-500/20',
  'Query Management': 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  'Ticket Management': 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  'Analytics': 'text-pink-400 bg-pink-500/10 border-pink-500/20',
}

export default function PermissionsPage() {
  const [search, setSearch] = useState('')
  const [openCats, setOpenCats] = useState<Set<string>>(new Set(['User Management']))

  const totalPerms = STATIC_CATALOG.reduce((acc, c) => acc + c.permissions.length, 0)
  const toggle = (cat: string) => setOpenCats(prev => {
    const next = new Set(prev)
    next.has(cat) ? next.delete(cat) : next.add(cat)
    return next
  })

  const filtered = STATIC_CATALOG.map(cat => ({
    ...cat,
    permissions: cat.permissions.filter(p =>
      !search || p.label.toLowerCase().includes(search.toLowerCase()) ||
      p.key.toLowerCase().includes(search.toLowerCase()) ||
      p.description.toLowerCase().includes(search.toLowerCase())
    ),
  })).filter(cat => cat.permissions.length > 0)

  return (
    <PermissionGate permission={Permission.PERMISSION_MANAGE}>
      <AdminSectionShell
        title="Permission Catalog"
        description="All fine-grained permissions in the system, organized by functional category."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Permissions' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-violet-500/15 text-violet-300 border border-violet-500/20">{totalPerms} permissions</span>}
      >
        {/* Search */}
        <div className="relative mb-5">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search permissions..."
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-blue-500/50 focus:bg-white/[0.06]"
          />
        </div>

        <div className="space-y-2">
          {filtered.map(cat => (
            <div key={cat.category} className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
              <button
                onClick={() => toggle(cat.category)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.03] transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${CAT_COLORS[cat.category] ?? 'text-white/50 bg-white/[0.05] border-white/10'}`}>
                    {cat.category}
                  </span>
                  <span className="text-xs text-white/30">{cat.permissions.length} permissions</span>
                </div>
                <motion.div animate={{ rotate: openCats.has(cat.category) ? 180 : 0 }} transition={{ duration: 0.15 }}>
                  <ChevronDown className="w-4 h-4 text-white/30" />
                </motion.div>
              </button>

              {openCats.has(cat.category) && (
                <div className="px-4 pb-3 grid grid-cols-1 gap-1.5">
                  {cat.permissions.map(p => (
                    <div key={p.key} className="flex items-start gap-3 p-3 bg-white/[0.02] rounded-lg border border-white/[0.04]">
                      <KeyRound className="w-3.5 h-3.5 text-white/30 mt-0.5 flex-shrink-0" />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-xs font-medium text-white/80">{p.label}</p>
                          <code className="text-[10px] text-white/25 font-mono">{p.key}</code>
                        </div>
                        <p className="text-[11px] text-white/40 mt-0.5">{p.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </AdminSectionShell>
    </PermissionGate>
  )
}
