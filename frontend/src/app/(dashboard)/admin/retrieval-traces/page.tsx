'use client'
import { useCallback, useEffect, useState } from 'react'
import { Zap, Search, ChevronDown, ChevronUp, Loader2, Eye } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { queryLogsApi, type QueryLogListItem, type QueryLogDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

const ROUTE_COLORS: Record<string, string> = {
  vector: 'bg-blue-500/15 text-blue-300 border-blue-500/20',
  bm25: 'bg-amber-500/15 text-amber-300 border-amber-500/20',
  hybrid: 'bg-violet-500/15 text-violet-300 border-violet-500/20',
  graph: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/20',
}

function ExpandedTrace({ log }: { log: any }) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      className="overflow-hidden"
    >
      <div className="px-4 py-4 border-t border-gray-200 dark:border-white/[0.05] bg-gray-50/50 dark:bg-white/[0.01] grid grid-cols-2 gap-4">
        <div>
          <p className="text-[10px] text-gray-500 dark:text-white/30 uppercase tracking-wider mb-2">Query</p>
          <p className="text-xs text-gray-800 dark:text-white/70 leading-relaxed font-medium">{log.query_text}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 dark:text-white/30 uppercase tracking-wider mb-2">Answer</p>
          <p className="text-xs text-gray-600 dark:text-white/60 leading-relaxed line-clamp-4">{log.answer_text || '—'}</p>
        </div>
        <div className="col-span-2 grid grid-cols-4 gap-3">
          {[
            { label: 'Query ID', value: log.query_id, mono: true },
            { label: 'Intent', value: log.intent ?? '—' },
            { label: 'Retrieved Chunks', value: log.retrieved_chunks ?? '—' },
            { label: 'Hallucinations', value: log.hallucinations_detected ?? 0 },
            { label: 'Retrieval Latency', value: log.retrieval_latency_ms ? `${Math.round(log.retrieval_latency_ms)}ms` : '—' },
            { label: 'LLM Latency', value: log.llm_latency_ms ? `${Math.round(log.llm_latency_ms)}ms` : '—' },
            { label: 'Rerank Latency', value: log.reranking_latency_ms ? `${Math.round(log.reranking_latency_ms)}ms` : '—' },
            { label: 'Was Rewritten', value: log.was_rewritten ? 'Yes' : 'No' },
          ].map(item => (
            <div key={item.label} className="bg-gray-100 dark:bg-white/[0.03] rounded-lg p-2.5">
              <p className="text-[10px] text-gray-500 dark:text-white/30 mb-1">{item.label}</p>
              <p className={`text-xs text-gray-700 dark:text-white/65 ${item.mono ? 'font-mono text-[10px]' : ''}`}>{String(item.value)}</p>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  )
}

export default function RetrievalTracesPage() {
  const [logs, setLogs] = useState<QueryLogListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await queryLogsApi.list({ skip: 0, limit: 50 })
      setLogs(res.logs)
    } catch (e) { setError('Failed to load traces') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = logs.filter(l =>
    !search || l.query_text.toLowerCase().includes(search.toLowerCase()) || l.query_id.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <PermissionGate permission={Permission.QUERY_LOG_VIEW_GLOBAL}>
      <AdminSectionShell
        title="Retrieval Traces"
        description="Detailed per-query retrieval traces: latency breakdown, intent, chunks retrieved, and rewriting."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Retrieval Traces' }]}
      >
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-white/30" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search queries or IDs…"
            className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-gray-400 dark:text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading traces…</span>
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map(log => {
              const isOpen = expandedId === log.query_id
              const conf = log.confidence_score
              return (
                <div key={log.query_id} className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden hover:border-gray-300 dark:hover:border-white/10 transition-colors shadow-sm">
                  <button className="w-full flex items-center gap-4 px-4 py-3 text-left" onClick={() => setExpandedId(isOpen ? null : log.query_id)}>
                    <Zap className="w-4 h-4 text-amber-500 dark:text-amber-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-800 dark:text-white/75 font-medium truncate">{log.query_text}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] border ${ROUTE_COLORS[log.route ?? ''] ?? 'bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-white/40 border-gray-200 dark:border-white/10'}`}>{log.route}</span>
                        {log.intent && <span className="text-[10px] text-gray-500 dark:text-white/30">{log.intent}</span>}
                        <span className="text-[10px] text-gray-400 dark:text-white/25">{formatDateTime(log.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 flex-shrink-0">
                      {conf !== undefined && conf !== null && (
                        <span className={`text-xs font-mono font-semibold ${conf >= 0.7 ? 'text-emerald-600 dark:text-emerald-400' : conf >= 0.45 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}`}>
                          {Math.round(conf * 100)}%
                        </span>
                      )}
                      <span className="text-[11px] text-gray-400 dark:text-white/25">{log.latency_ms ? `${Math.round(log.latency_ms)}ms` : ''}</span>
                      {isOpen ? <ChevronUp className="w-4 h-4 text-gray-400 dark:text-white/30" /> : <ChevronDown className="w-4 h-4 text-gray-400 dark:text-white/20" />}
                    </div>
                  </button>
                  <AnimatePresence>
                    {isOpen && <ExpandedTrace log={log} />}
                  </AnimatePresence>
                </div>
              )
            })}
            {filtered.length === 0 && (
              <div className="text-center py-10 text-sm text-gray-400 dark:text-white/30">No traces found</div>
            )}
          </div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
