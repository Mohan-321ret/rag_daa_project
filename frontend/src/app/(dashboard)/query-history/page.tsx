'use client'
import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Search, Filter, Download, AlertTriangle, CheckCircle, ChevronDown, ChevronUp, Calendar } from 'lucide-react'
import { PageHeader, Card, StatusBadge, ConfidenceMeter } from '@/components/shared/index'
import { formatDateTime, formatLatency } from '@/lib/utils'
import { queryLogsApi } from '@/lib/api'
import Link from 'next/link'
import type { QueryLogListItem } from '@/types'

interface FilterState {
  search: string
  intent: string
  route: string
  model: string
  confidenceMin: number | null
  confidenceMax: number | null
  ticketStatus: string
  verificationResult: string
  retrievalStrategy: string
  skip: number
  limit: number
}

export default function QueryHistoryPage() {
  const [logs, setLogs] = useState<QueryLogListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [filters, setFilters] = useState<FilterState>({
    search: '',
    intent: '',
    route: '',
    model: '',
    confidenceMin: null,
    confidenceMax: null,
    ticketStatus: '',
    verificationResult: '',
    retrievalStrategy: '',
    skip: 0,
    limit: 50,
  })
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)

  useEffect(() => {
    loadQueryLogs()
  }, [filters.skip, filters.limit])

  const loadQueryLogs = async () => {
    setLoading(true)
    try {
      const response = await queryLogsApi.list({
        skip: filters.skip,
        limit: filters.limit,
        search_text: filters.search || undefined,
        intent: filters.intent || undefined,
        route: filters.route || undefined,
        model_used: filters.model || undefined,
        min_confidence: filters.confidenceMin !== null ? filters.confidenceMin : undefined,
        max_confidence: filters.confidenceMax !== null ? filters.confidenceMax : undefined,
        ticket_status: filters.ticketStatus || undefined,
        verification_result: filters.verificationResult || undefined,
        retrieval_strategy: filters.retrievalStrategy || undefined,
      })
      setLogs(response.logs)
      setTotal(response.total)
    } catch (error) {
      console.error('Failed to load query logs:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = () => {
    setFilters(f => ({ ...f, skip: 0 }))
    loadQueryLogs()
  }

  const handleClearFilters = () => {
    setFilters({
      search: '',
      intent: '',
      route: '',
      model: '',
      confidenceMin: null,
      confidenceMax: null,
      ticketStatus: '',
      verificationResult: '',
      retrievalStrategy: '',
      skip: 0,
      limit: 50,
    })
  }

  const handleExport = async () => {
    try {
      const response = await queryLogsApi.export({
        search_text: filters.search || undefined,
        intent: filters.intent || undefined,
        route: filters.route || undefined,
        model_used: filters.model || undefined,
        min_confidence: filters.confidenceMin !== null ? filters.confidenceMin : undefined,
        max_confidence: filters.confidenceMax !== null ? filters.confidenceMax : undefined,
        ticket_status: filters.ticketStatus || undefined,
        verification_result: filters.verificationResult || undefined,
        retrieval_strategy: filters.retrievalStrategy || undefined,
      })
      const dataStr = JSON.stringify(response.logs, null, 2)
      const dataBlob = new Blob([dataStr], { type: 'application/json' })
      const url = URL.createObjectURL(dataBlob)
      const link = document.createElement('a')
      link.href = url
      link.download = `query-logs-${new Date().toISOString().split('T')[0]}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to export query logs:', error)
    }
  }

  const methodColors: Record<string, string> = {
    hybrid: 'bg-blue-50 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400',
    vector: 'bg-violet-50 text-violet-700 dark:bg-violet-500/20 dark:text-violet-400',
    bm25: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400',
    graph: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-500/20 dark:text-cyan-400',
  }

  const verificationColors: Record<string, string> = {
    verified: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400',
    partial: 'bg-amber-50 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400',
    unverified: 'bg-gray-100 text-gray-600 dark:bg-gray-500/20 dark:text-gray-400',
    failed: 'bg-red-50 text-red-700 dark:bg-red-500/20 dark:text-red-400',
  }

  return (
    <div className="space-y-6">
      <PageHeader 
        title="Query History & Logs" 
        description="View and analyze all queries with detailed information, verification results, and performance metrics"
      />

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Queries', value: total, color: 'text-blue-600 dark:text-blue-400' },
          { label: 'Page', value: `${Math.floor(filters.skip / filters.limit) + 1}`, color: 'text-violet-600 dark:text-violet-400' },
          { label: 'Verified', value: logs.filter(q => q.verification_result === 'verified').length, color: 'text-emerald-600 dark:text-emerald-400' },
          { label: 'Issues', value: logs.filter(q => q.hallucinations_detected > 0).length, color: 'text-red-600 dark:text-red-400' },
        ].map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className="bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl p-4">
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-[11px] text-gray-500 dark:text-white/40 mt-1 font-medium">{s.label}</p>
          </motion.div>
        ))}
      </div>

      {/* Main Search */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 flex-1">
          <Search className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
          <input 
            value={filters.search} 
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
            onKeyUp={e => e.key === 'Enter' && handleSearch()}
            placeholder="Search query text or answers..." 
            className="bg-transparent text-xs text-gray-900 dark:text-white/60 placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none flex-1" 
          />
        </div>
        <button
          onClick={handleSearch}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-medium transition-colors shadow-sm"
        >
          Search
        </button>
        <button
          onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
          className="px-4 py-2 bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] hover:bg-gray-200 dark:hover:bg-white/[0.08] text-gray-700 dark:text-white rounded-xl text-xs font-medium transition-colors flex items-center gap-2"
        >
          <Filter className="w-3.5 h-3.5" />
          Filters
        </button>
        <button
          onClick={handleExport}
          className="px-4 py-2 bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] hover:bg-gray-200 dark:hover:bg-white/[0.08] text-gray-700 dark:text-white rounded-xl text-xs font-medium transition-colors flex items-center gap-2"
        >
          <Download className="w-3.5 h-3.5" />
          Export
        </button>
      </div>

      {/* Advanced Filters */}
      {showAdvancedFilters && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.07] rounded-2xl p-4"
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Intent</label>
              <select
                value={filters.intent}
                onChange={e => setFilters(f => ({ ...f, intent: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="informational" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Informational</option>
                <option value="navigational" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Navigational</option>
                <option value="transactional" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Transactional</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Retrieval Route</label>
              <select
                value={filters.route}
                onChange={e => setFilters(f => ({ ...f, route: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="vector" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Vector</option>
                <option value="bm25" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">BM25</option>
                <option value="hybrid" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Hybrid</option>
                <option value="graph" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Graph</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Model</label>
              <select
                value={filters.model}
                onChange={e => setFilters(f => ({ ...f, model: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="gpt-4" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">GPT-4</option>
                <option value="gpt-3.5" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">GPT-3.5</option>
                <option value="claude-3" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Claude 3</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Verification</label>
              <select
                value={filters.verificationResult}
                onChange={e => setFilters(f => ({ ...f, verificationResult: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="verified" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Verified</option>
                <option value="partial" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Partial</option>
                <option value="unverified" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Unverified</option>
                <option value="failed" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Failed</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Min Confidence</label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={filters.confidenceMin ?? ''}
                onChange={e => setFilters(f => ({ ...f, confidenceMin: e.target.value ? parseFloat(e.target.value) : null }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none"
                placeholder="0.0"
              />
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Max Confidence</label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={filters.confidenceMax ?? ''}
                onChange={e => setFilters(f => ({ ...f, confidenceMax: e.target.value ? parseFloat(e.target.value) : null }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none"
                placeholder="1.0"
              />
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Ticket Status</label>
              <select
                value={filters.ticketStatus}
                onChange={e => setFilters(f => ({ ...f, ticketStatus: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="open" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Open</option>
                <option value="in_review" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">In Review</option>
                <option value="resolved" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Resolved</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-600 dark:text-white/40 mb-2 block font-medium">Retrieval Strategy</label>
              <select
                value={filters.retrievalStrategy}
                onChange={e => setFilters(f => ({ ...f, retrievalStrategy: e.target.value }))}
                className="w-full bg-white dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg px-2 py-1.5 text-xs text-gray-900 dark:text-white outline-none"
              >
                <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All</option>
                <option value="vector" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Vector</option>
                <option value="bm25" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">BM25</option>
                <option value="adaptive" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Adaptive</option>
              </select>
            </div>
          </div>

          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium transition-colors shadow-sm"
            >
              Apply Filters
            </button>
            <button
              onClick={handleClearFilters}
              className="px-4 py-2 bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] hover:bg-gray-200 dark:hover:bg-white/[0.08] text-gray-700 dark:text-white rounded-lg text-xs font-medium transition-colors"
            >
              Clear All
            </button>
          </div>
        </motion.div>
      )}

      {/* Query List */}
      <div className="space-y-2">
        {loading ? (
          <div className="text-center py-8 text-gray-500 dark:text-white/40 font-medium">Loading query logs...</div>
        ) : logs.length === 0 ? (
          <div className="text-center py-8 text-gray-500 dark:text-white/40 font-medium">No query logs found</div>
        ) : (
          logs.map((log, i) => (
            <motion.div key={log.query_id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.02 }}
              className="bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl overflow-hidden">
              <Link href={`/query-history/${log.query_id}`}>
                <button className="w-full flex items-center gap-4 p-4 text-left hover:bg-gray-100/60 dark:hover:bg-white/[0.02] transition-colors"
                  onClick={(e) => {
                    if (expanded === log.query_id) {
                      e.preventDefault()
                      setExpanded(null)
                    }
                  }}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {log.hallucinations_detected > 0 ? 
                        <AlertTriangle className="w-3.5 h-3.5 text-red-500 dark:text-red-400 flex-shrink-0" /> : 
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400 flex-shrink-0" />
                      }
                      <p className="text-sm text-gray-900 dark:text-white/80 truncate font-medium">{log.query_text}</p>
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-gray-500 dark:text-white/40 flex-wrap">
                      <span>{formatDateTime(log.created_at)}</span>
                      {log.intent && (
                        <>
                          <span>·</span>
                          <span className="capitalize font-medium">{log.intent}</span>
                        </>
                      )}
                      {log.route && (
                        <>
                          <span>·</span>
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${methodColors[log.route as keyof typeof methodColors]}`}>
                            {log.route}
                          </span>
                        </>
                      )}
                      {log.verification_result && (
                        <>
                          <span>·</span>
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${verificationColors[log.verification_result as keyof typeof verificationColors]}`}>
                            {log.verification_result}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0">
                    <div className="text-right">
                      <p className="text-xs font-semibold text-gray-800 dark:text-white/70">{log.latency_ms ? formatLatency(log.latency_ms) : 'N/A'}</p>
                      <p className="text-[10px] text-gray-400 dark:text-white/30">latency</p>
                    </div>
                    {log.confidence_score !== undefined && (
                      <div className="w-20">
                        <ConfidenceMeter value={log.confidence_score} size="sm" />
                      </div>
                    )}
                    {expanded === log.query_id ? <ChevronUp className="w-4 h-4 text-gray-400 dark:text-white/30" /> : <ChevronDown className="w-4 h-4 text-gray-400 dark:text-white/30" />}
                  </div>
                </button>
              </Link>

              {expanded === log.query_id && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="border-t border-gray-200 dark:border-white/[0.06] p-4 bg-gray-100/50 dark:bg-white/[0.01]">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-[10px] text-gray-400 dark:text-white/30 mb-1">Complexity</p>
                      <p className="text-xs font-semibold text-gray-800 dark:text-white/70 capitalize">{log.complexity || 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-400 dark:text-white/30 mb-1">Retrieved Chunks</p>
                      <p className="text-xs font-semibold text-gray-800 dark:text-white/70">{log.retrieved_chunks}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-400 dark:text-white/30 mb-1">Citations</p>
                      <p className="text-xs font-semibold text-gray-800 dark:text-white/70">{log.citation_count}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-400 dark:text-white/30 mb-1">Grounded</p>
                      <p className={`text-xs font-semibold ${log.is_grounded ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-500 dark:text-gray-400'}`}>
                        {log.is_grounded ? 'Yes' : 'No'}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4">
                    <Link href={`/query-history/${log.query_id}`}>
                      <button className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-semibold">
                        View Full Trace →
                      </button>
                    </Link>
                  </div>
                </motion.div>
              )}
            </motion.div>
          ))
        )}
      </div>

      {/* Pagination */}
      {total > filters.limit && (
        <div className="flex items-center justify-between pt-4">
          <button
            onClick={() => setFilters(f => ({ ...f, skip: Math.max(0, f.skip - f.limit) }))}
            disabled={filters.skip === 0}
            className="px-4 py-2 bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg text-xs font-medium text-gray-700 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-200 dark:hover:bg-white/[0.08] transition-colors"
          >
            Previous
          </button>
          <p className="text-xs text-gray-500 dark:text-white/40">
            Showing {filters.skip + 1}-{Math.min(filters.skip + filters.limit, total)} of {total}
          </p>
          <button
            onClick={() => setFilters(f => ({ ...f, skip: f.skip + f.limit }))}
            disabled={filters.skip + filters.limit >= total}
            className="px-4 py-2 bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.07] rounded-lg text-xs font-medium text-gray-700 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-200 dark:hover:bg-white/[0.08] transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
