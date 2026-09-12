'use client'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { Ticket, Search, Loader2, UserCheck, Inbox, CheckCircle, Globe2, RefreshCw } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { ticketsApi, type TicketOut, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Btn } from '@/components/shared/index'

type Tab = 'all' | 'domains' | 'assigned' | 'unassigned' | 'resolved'

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/15 dark:text-red-400 dark:border-red-500/20',
  medium: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/15 dark:text-amber-400 dark:border-amber-500/20',
  low: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/20',
  critical: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-600/20 dark:text-red-300 dark:border-red-600/30',
}

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/20',
  pending: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-500/20',
  in_progress: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:border-violet-500/20',
  resolved: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/20',
  closed: 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-white/[0.06] dark:text-white/40 dark:border-white/10',
}

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'all',       label: 'All Tickets',      icon: Ticket },
  { id: 'domains',   label: 'Domain Queues',     icon: Globe2 },
  { id: 'assigned',  label: 'Assigned',          icon: UserCheck },
  { id: 'unassigned',label: 'Unassigned',        icon: Inbox },
  { id: 'resolved',  label: 'Resolved',          icon: CheckCircle },
]

export default function AdminTicketsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('all')
  const [tickets, setTickets] = useState<TicketOut[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 20

  // Sync tab state with query parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
    } else {
      setTab('all')
    }
  }, [tabParam])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { skip: page * PAGE_SIZE, limit: PAGE_SIZE }
      if (tab === 'resolved') params.status = 'resolved'
      if (tab === 'unassigned') params.assigned = false
      if (tab === 'assigned') params.assigned = true
      const res = await ticketsApi.list(params)
      setTickets(res.tickets)
      setTotal(res.total)
    } catch {}
    finally { setLoading(false) }
  }, [tab, page])

  useEffect(() => { setPage(0) }, [tab])
  useEffect(() => { load() }, [load])

  const filtered = tickets.filter(t =>
    !search ||
    t.title?.toLowerCase().includes(search.toLowerCase()) ||
    t.ticket_id.toLowerCase().includes(search.toLowerCase()) ||
    t.query_text?.toLowerCase().includes(search.toLowerCase())
  )

  const byDomain = filtered.reduce((acc, t) => {
    const key = t.domain ?? 'Unassigned'
    if (!acc[key]) acc[key] = []
    acc[key].push(t)
    return acc
  }, {} as Record<string, TicketOut[]>)

  const selectTab = (t: Tab) => {
    router.push(`/admin/tickets?tab=${t}`)
  }

  return (
    <PermissionGate permission={[Permission.TICKET_VIEW_DOMAIN, Permission.TICKET_ASSIGN]} any>
      <AdminSectionShell
        title="Ticket Management"
        description="View and manage all review tickets across the platform."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Tickets' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:border-rose-500/20">{total} tickets</span>}
        action={
          <Btn size="sm" variant="ghost" onClick={load} className="flex items-center gap-1.5 text-xs">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </Btn>
        }
      >
        {/* Tabs */}
        <div className="flex items-center gap-1 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 w-fit mb-5 flex-wrap">
          {TABS.map(t => {
            const Icon = t.icon
            return (
              <button key={t.id} onClick={() => selectTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-rose-600 text-white shadow-sm' : 'text-gray-600 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'}`}>
                <Icon className="w-3.5 h-3.5" />{t.label}
              </button>
            )
          })}
        </div>

        {/* Search */}
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-white/30" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tickets…"
            className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 rounded-xl pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:border-rose-500 transition-all"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-adaptive-secondary">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading tickets…</span>
          </div>
        ) : tab === 'domains' ? (
          // Domain queue view
          <div className="space-y-4">
            {Object.entries(byDomain).map(([domain, items]) => (
              <div key={domain} className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden shadow-sm dark:shadow-none">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-white/[0.05]">
                  <Globe2 className="w-4 h-4 text-cyan-600 dark:text-cyan-400" />
                  <span className="text-sm font-medium text-adaptive-primary">{domain}</span>
                  <span className="ml-auto text-xs text-adaptive-muted">{items.length} tickets</span>
                </div>
                {items.slice(0, 5).map(t => (
                  <TicketRow key={t.ticket_id} ticket={t} />
                ))}
                {items.length > 5 && (
                  <div className="px-4 py-2 text-xs text-adaptive-muted border-t border-gray-100 dark:border-white/[0.04]">+{items.length - 5} more</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          // Standard list view
          <div className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden shadow-sm dark:shadow-none">
            {filtered.length === 0 ? (
              <div className="py-10 text-center text-sm text-adaptive-muted">No tickets found</div>
            ) : filtered.map(t => <TicketRow key={t.ticket_id} ticket={t} />)}
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between mt-4">
            <p className="text-xs text-adaptive-muted">Page {page + 1}</p>
            <div className="flex gap-2">
              <Btn size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</Btn>
              <Btn size="sm" variant="ghost" disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Btn>
            </div>
          </div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}

function TicketRow({ ticket: t }: { ticket: TicketOut }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-white/[0.04] last:border-0 hover:bg-gray-50 dark:hover:bg-white/[0.02] transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <p className="text-sm text-gray-800 dark:text-white/75 truncate font-medium">{t.title ?? t.query_text ?? t.ticket_id}</p>
          {t.priority && (
            <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${PRIORITY_COLORS[t.priority] ?? 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-white/[0.06] dark:text-white/40 dark:border-white/10'}`}>
              {t.priority}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono text-gray-400 dark:text-white/25">{t.ticket_id}</span>
          {t.domain && <span className="text-[10px] text-gray-500 dark:text-white/30">{t.domain}</span>}
          <span className="text-[10px] text-gray-400 dark:text-white/20">{formatDateTime(t.created_at)}</span>
        </div>
      </div>
      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border flex-shrink-0 ${STATUS_COLORS[t.status] ?? 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-white/[0.06] dark:text-white/40 dark:border-white/10'}`}>
        {t.status}
      </span>
    </motion.div>
  )
}
