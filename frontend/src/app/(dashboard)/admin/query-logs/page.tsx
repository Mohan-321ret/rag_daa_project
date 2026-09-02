'use client'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { ScrollText, Search, Download, Filter, RefreshCw, Loader2, Clock, Zap, Brain } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { queryLogsApi, type QueryLogListItem, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Btn } from '@/components/shared/index'

const ROUTE_COLORS: Record<string, string> = {
  vector: 'bg-blue-500/15 text-blue-300 border-blue-500/20',
  bm25: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  hybrid: 'bg-violet-500/15 text-violet-300 border-violet-500/20',
  graph: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/20',
  keyword: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
}

function ConfidencePill({ score }: { score?: number }) {
  if (score === undefined || score === null) return <span className="text-white/25">—</span>
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? 'text-emerald-400' : pct >= 45 ? 'text-amber-400' : 'text-red-400'
  return <span className={`font-mono text-xs ${color}`}>{pct}%</span>
}

type Tab = 'logs' | 'history'

export default function QueryLogsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('logs')
  const [logs, setLogs] = useState<QueryLogListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [routeFilter, setRouteFilter] = useState('')
  const [page, setPage] = useState(0)
  const [total, setTotal] = useState(0)
  const PAGE_SIZE = 25

  // Sync tab state with query parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
    } else {
      setTab('logs')
    }
  }, [tabParam])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      // In query history mode, we can show user-scoped or extra filter query logs if backend supported it,
      // otherwise list lists the query logs matching the query.
      const res = await queryLogsApi.list({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        search_text: search || undefined,
        route: routeFilter || undefined
      })
      setLogs(res.logs)
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load query logs')
    } finally { setLoading(false) }
  }, [page, search, routeFilter])

  useEffect(() => { load() }, [load])

  const TABS = [
    { id: 'logs' as Tab, label: 'Query Logs' },
    { id: 'history' as Tab, label: 'Query History' },
  ]

  const selectTab = (t: Tab) => {
    router.push(`/admin/query-logs?tab=${t}`)
  }

  return (
    <PermissionGate permission={[Permission.QUERY_LOG_VIEW_GLOBAL, Permission.QUERY_LOG_VIEW_DOMAIN]} any>
      <AdminSectionShell
        title="Query Management"
        description="View, search and export query logs across the platform."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Query Logs' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-amber-500/15 text-amber-300 border border-amber-500/20">{total} queries</span>}
        action={
          <Btn size="sm" variant="ghost" className="flex items-center gap-1.5 text-xs" onClick={load}>
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </Btn>
        }
      >
        {/* Tabs */}
        <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 w-fit mb-5">
          {TABS.map(t => (
            <button key={t.id} onClick={() => selectTab(t.id)}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
            <input value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} placeholder="Search queries…"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-blue-500/50"
            />
          </div>
          <select value={routeFilter} onChange={e => { setRouteFilter(e.target.value); setPage(0) }}
            className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-sm text-white/70 focus:outline-none min-w-32">
            <option value="">All Routes</option>
            {['vector', 'bm25', 'hybrid', 'graph', 'keyword'].map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading…</span>
          </div>
        ) : error ? (
          <p className="text-center text-sm text-red-400 py-10">{error}</p>
        ) : (
          <>
            <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/[0.06]">
                    <th className="text-left px-4 py-3 text-white/35 font-medium">Query</th>
                    <th className="text-left px-4 py-3 text-white/35 font-medium w-24">Route</th>
                    <th className="text-left px-4 py-3 text-white/35 font-medium w-24">Confidence</th>
                    <th className="text-left px-4 py-3 text-white/35 font-medium w-28">Latency</th>
                    <th className="text-left px-4 py-3 text-white/35 font-medium w-36">Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map(log => (
                    <tr key={log.query_id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3">
                        <p className="text-white/75 truncate max-w-xs">{log.query_text}</p>
                        <p className="text-white/30 font-mono text-[10px] mt-0.5">{log.query_id}</p>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${ROUTE_COLORS[log.route ?? ''] ?? 'bg-white/[0.06] text-white/40 border-white/10'}`}>
                          {log.route}
                        </span>
                      </td>
                      <td className="px-4 py-3"><ConfidencePill score={log.confidence_score} /></td>
                      <td className="px-4 py-3">
                        {log.latency_ms
                          ? <span className="text-white/50 flex items-center gap-1"><Clock className="w-3 h-3" />{Math.round(log.latency_ms)}ms</span>
                          : <span className="text-white/25">—</span>}
                      </td>
                      <td className="px-4 py-3 text-white/35">{formatDateTime(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {logs.length === 0 && (
                <div className="py-10 text-center text-sm text-white/30">No query logs found</div>
              )}
            </div>

            {/* Pagination */}
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-xs text-white/30">Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</p>
                <div className="flex gap-2">
                  <Btn size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</Btn>
                  <Btn size="sm" variant="ghost" disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Btn>
                </div>
              </div>
            )}
          </>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
