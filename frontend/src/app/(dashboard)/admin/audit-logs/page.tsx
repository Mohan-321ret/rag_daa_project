'use client'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { ScrollText, Search, Filter, Clock, User, KeyRound, FileText, Boxes, Cpu, Ticket, Loader2, RefreshCw } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { formatDateTime } from '@/lib/utils'
import { Btn } from '@/components/shared/index'

type Tab = 'users' | 'permissions' | 'documents' | 'indexing' | 'llm' | 'tickets'

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }>; color: string }[] = [
  { id: 'users',       label: 'User Changes',       icon: User,      color: 'bg-blue-600' },
  { id: 'permissions', label: 'Permission Changes',  icon: KeyRound,  color: 'bg-violet-600' },
  { id: 'documents',   label: 'Document Actions',    icon: FileText,  color: 'bg-emerald-600' },
  { id: 'indexing',    label: 'Indexing Actions',    icon: Boxes,     color: 'bg-cyan-600' },
  { id: 'llm',         label: 'LLM Changes',         icon: Cpu,       color: 'bg-purple-600' },
  { id: 'tickets',     label: 'Ticket Actions',      icon: Ticket,    color: 'bg-rose-600' },
]

interface AuditEvent {
  id: string
  timestamp: string
  actor: string
  action: string
  resource: string
  category: Tab
  severity: 'info' | 'warning' | 'critical'
  details?: string
}

const SEVERITY_COLORS = {
  info:     'bg-blue-500/10 text-blue-300 border-blue-500/20',
  warning:  'bg-amber-500/10 text-amber-300 border-amber-500/20',
  critical: 'bg-red-500/10 text-red-300 border-red-500/20',
}

const ACTION_ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  'User created': User, 'User deactivated': User, 'Role assigned': KeyRound,
  'Domain assigned': Boxes, 'Document uploaded': FileText, 'Document deleted': FileText,
  'Ingestion started': Boxes, 'Chunk re-indexed': Boxes, 'LLM model changed': Cpu,
  'Ticket resolved': Ticket, 'Ticket assigned': Ticket, 'Permission viewed': KeyRound,
}

function generateMockEvents(category: Tab): AuditEvent[] {
  const now = Date.now()
  const actors = ['admin@example.com', 'manager@corp.com', 'system', 'analyst@org.com']
  const templates: Record<Tab, Array<{ action: string; resource: string; severity: AuditEvent['severity'] }>> = {
    users: [
      { action: 'User created', resource: 'employee@corp.com', severity: 'info' },
      { action: 'User deactivated', resource: 'old.user@corp.com', severity: 'warning' },
      { action: 'Role assigned', resource: 'analyst role → user#42', severity: 'info' },
      { action: 'User updated', resource: 'profile fields changed', severity: 'info' },
    ],
    permissions: [
      { action: 'Permission viewed', resource: 'permission catalog', severity: 'info' },
      { action: 'Role assigned', resource: 'super_admin → user#7', severity: 'critical' },
      { action: 'Domain assigned', resource: 'HR domain → user#12', severity: 'info' },
    ],
    documents: [
      { action: 'Document uploaded', resource: 'Q4_Financial_Report.pdf', severity: 'info' },
      { action: 'Document deleted', resource: 'old_policy_v1.docx', severity: 'warning' },
      { action: 'Document updated', resource: 'Employee_Handbook.pdf', severity: 'info' },
    ],
    indexing: [
      { action: 'Ingestion started', resource: 'folder-watcher triggered', severity: 'info' },
      { action: 'Chunk re-indexed', resource: '247 chunks from doc#88', severity: 'info' },
      { action: 'Index rebuild', resource: 'Full FAISS rebuild initiated', severity: 'warning' },
    ],
    llm: [
      { action: 'LLM model changed', resource: 'gpt-4o → gpt-4o-mini', severity: 'warning' },
      { action: 'LLM provider updated', resource: 'OpenAI config updated', severity: 'info' },
      { action: 'Connection test', resource: 'ping OK — 342ms', severity: 'info' },
    ],
    tickets: [
      { action: 'Ticket resolved', resource: 'TKT_A1B2C3 (EXPERT_ANSWER)', severity: 'info' },
      { action: 'Ticket assigned', resource: 'TKT_D4E5F6 → analyst@org.com', severity: 'info' },
      { action: 'Ticket closed', resource: 'TKT_G7H8I9 dismissed', severity: 'warning' },
    ],
  }
  return templates[category].flatMap((t, ti) =>
    Array.from({ length: 4 }, (_, i) => ({
      id: `${category}-${ti}-${i}`,
      timestamp: new Date(now - (ti * 4 + i) * 3600000).toISOString(),
      actor: actors[(ti + i) % actors.length],
      action: t.action,
      resource: t.resource,
      category,
      severity: t.severity,
      details: i === 0 ? 'Via admin panel' : undefined,
    }))
  ).sort((a, b) => b.timestamp.localeCompare(a.timestamp))
}

export default function AuditLogsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('users')
  const [search, setSearch] = useState('')
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(false)

  // Sync tab state with query parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
    } else {
      setTab('users')
    }
  }, [tabParam])

  const load = useCallback(() => {
    setLoading(true)
    setTimeout(() => {
      setEvents(generateMockEvents(tab))
      setLoading(false)
    }, 300)
  }, [tab])

  useEffect(() => { load() }, [load])

  const filtered = events.filter(e =>
    !search ||
    e.action.toLowerCase().includes(search.toLowerCase()) ||
    e.resource.toLowerCase().includes(search.toLowerCase()) ||
    e.actor.toLowerCase().includes(search.toLowerCase())
  )

  const selectTab = (t: Tab) => {
    router.push(`/admin/audit-logs?tab=${t}`)
  }

  return (
    <PermissionGate permission={[Permission.USER_READ, Permission.QUERY_LOG_VIEW_GLOBAL]} any>
      <AdminSectionShell
        title="Audit Logs"
        description="Searchable audit trail of all administrative actions across the platform."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Audit Logs' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-orange-500/15 text-orange-300 border border-orange-500/20">Live feed</span>}
        action={
          <Btn size="sm" variant="ghost" onClick={load} className="flex items-center gap-1.5 text-xs">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </Btn>
        }
      >
        {/* Category Tabs */}
        <div className="flex flex-wrap gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 w-fit mb-5">
          {TABS.map(t => {
            const Icon = t.icon
            return (
              <button key={t.id} onClick={() => selectTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? `${t.color} text-white` : 'text-white/40 hover:text-white/70'}`}>
                <Icon className="w-3.5 h-3.5" />{t.label}
              </button>
            )
          })}
        </div>

        {/* Search */}
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search actions, actors, resources…"
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-orange-500/50"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading audit log…</span>
          </div>
        ) : (
          <div className="space-y-1.5">
            {filtered.map(event => {
              const ActionIcon = ACTION_ICON_MAP[event.action] ?? ScrollText
              return (
                <motion.div
                  key={event.id}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-start gap-3 p-3.5 bg-white/[0.02] border border-white/[0.05] rounded-xl hover:border-white/10 hover:bg-white/[0.03] transition-all"
                >
                  <div className="w-7 h-7 rounded-lg bg-white/[0.05] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <ActionIcon className="w-3.5 h-3.5 text-white/40" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-white/80">{event.action}</span>
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${SEVERITY_COLORS[event.severity]}`}>
                        {event.severity}
                      </span>
                    </div>
                    <p className="text-xs text-white/40 mt-0.5">{event.resource}</p>
                    {event.details && <p className="text-[11px] text-white/25 mt-0.5">{event.details}</p>}
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-[11px] text-white/30">{event.actor}</p>
                    <p className="text-[10px] text-white/20 mt-0.5 flex items-center gap-1 justify-end">
                      <Clock className="w-2.5 h-2.5" />{formatDateTime(event.timestamp)}
                    </p>
                  </div>
                </motion.div>
              )
            })}
            {filtered.length === 0 && (
              <div className="text-center py-10 text-white/30 text-sm">No audit events found</div>
            )}
          </div>
        )}

        <p className="text-[11px] text-white/20 mt-4">
          Note: Events currently sourced from simulated data. A dedicated audit-log backend endpoint will be added in a future phase.
        </p>
      </AdminSectionShell>
    </PermissionGate>
  )
}
