'use client'
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  Layers, CheckCircle, Clock, AlertCircle, XCircle, Loader2,
  RotateCcw, Trash2, RefreshCw, Eye, Search, HardDrive, Boxes, BarChart2,
} from 'lucide-react'
import { Can, PageHeader, Card, StatusBadge, Modal, Btn, ConfirmDialog, EmptyState } from '@/components/shared/index'
import { DataTable } from '@/components/shared/DataTable'
import {
  chunkIndexingApi, domainsApi, ApiError,
  type ChunkInspectOut, type ChunkIndexStatus, type DomainOut,
  type ReindexJobOut, type ReindexJobStatus,
} from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission } from '@/lib/rbac'

type ChunkRow = ChunkInspectOut & { id: string }
type JobRow = ReindexJobOut & { id: string }

type Tab = 'explorer' | 'status' | 'reindex' | 'failed' | 'stale'

const CHUNK_FILTERS: { id: ChunkIndexStatus | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'indexed', label: 'Indexed' },
  { id: 'pending', label: 'Pending' },
  { id: 'failed', label: 'Failed' },
  { id: 'stale', label: 'Stale' },
]

export default function ChunkIndexingDashboardPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('explorer')
  const [statusFilter, setStatusFilter] = useState<ChunkIndexStatus | 'all'>('all')
  const [domainFilter, setDomainFilter] = useState('')
  const [documentFilter, setDocumentFilter] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [reindexDomainId, setReindexDomainId] = useState('')
  const [inspecting, setInspecting] = useState<ReindexJobOut | null>(null)
  const [confirmRebuild, setConfirmRebuild] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const queryClient = useQueryClient()

  useEffect(() => { domainsApi.list().then(r => setDomains(r.domains)).catch(() => {}) }, [])

  // Sync tab with search parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
      if (tabParam === 'failed') setStatusFilter('failed')
      else if (tabParam === 'stale') setStatusFilter('stale')
      else if (tabParam === 'explorer') setStatusFilter('all')
    } else {
      setTab('explorer')
      setStatusFilter('all')
    }
  }, [tabParam])

  const { data: stats } = useQuery({
    queryKey: ['chunk-indexing-stats'],
    queryFn: () => chunkIndexingApi.stats(),
    refetchInterval: 5000,
  })

  const { data: chunkData, isLoading: chunksLoading, isError: chunksError, error: chunksErrObj, refetch: refetchChunks } = useQuery({
    queryKey: ['chunk-indexing-chunks', statusFilter, domainFilter, documentFilter, search, tab],
    queryFn: () => chunkIndexingApi.listChunks({
      status: statusFilter === 'all' ? undefined : statusFilter,
      domain_id: domainFilter || undefined,
      document_id: documentFilter || undefined,
      q: search || undefined,
      limit: 100,
    }),
  })

  const isJobActive = (j?: ReindexJobOut) => j?.status === 'queued' || j?.status === 'processing'

  const { data: jobData, isLoading: jobsLoading, isError: jobsError, error: jobsErrObj, refetch: refetchJobs } = useQuery({
    queryKey: ['chunk-indexing-jobs'],
    queryFn: () => chunkIndexingApi.listJobs({ limit: 50 }),
    refetchInterval: (query) => (query.state.data?.jobs ?? []).some(isJobActive) ? 3000 : 8000,
  })

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['chunk-indexing-chunks'] })
    queryClient.invalidateQueries({ queryKey: ['chunk-indexing-jobs'] })
    queryClient.invalidateQueries({ queryKey: ['chunk-indexing-stats'] })
  }

  const runAction = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key)
    setActionError(null)
    try {
      await fn()
      setSelected(new Set())
      refreshAll()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Action failed')
    } finally {
      setBusy(null)
    }
  }

  const chunkRows: ChunkRow[] = (chunkData?.chunks ?? []).map(c => ({ ...c, id: c.id }))
  const jobRows: JobRow[] = (jobData?.jobs ?? []).map(j => ({ ...j, id: j.job_id }))

  const toggleSelected = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelected(prev => {
      if (prev.size === chunkRows.length) return new Set()
      return new Set(chunkRows.map(r => r.id))
    })
  }

  const chunkColumns = [
    { key: 'select', label: '', render: (_: unknown, row: ChunkRow) => (
      <input type="checkbox" checked={selected.has(row.id)} onChange={() => toggleSelected(row.id)} onClick={e => e.stopPropagation()} className="rounded border-white/20 bg-white/[0.04]" />
    )},
    { key: 'text', label: 'Chunk Text', render: (v: unknown) => (
      <p className="text-xs text-white/70 max-w-sm truncate">{String(v)}</p>
    )},
    { key: 'status', label: 'Status', render: (v: unknown) => <StatusBadge status={String(v)} /> },
    { key: 'document_id', label: 'Document', render: (v: unknown) => <span className="text-[10px] font-mono text-white/40">{String(v)}</span> },
    { key: 'domain_name', label: 'Domain', render: (v: unknown) => <span className="text-xs text-white/50">{String(v || 'Global')}</span> },
    { key: 'updated_at', label: 'Last Indexed', render: (v: unknown) => <span className="text-[11px] text-white/30">{formatDateTime(String(v))}</span> },
  ]

  const jobColumns = [
    { key: 'job_id', label: 'Job ID', render: (v: unknown) => <span className="text-[11px] font-mono text-white/50">{String(v)}</span> },
    { key: 'job_type', label: 'Type', render: (v: unknown) => <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-white/[0.06] text-white/40">{String(v)}</span> },
    { key: 'status', label: 'Status', render: (v: unknown) => <StatusBadge status={String(v)} /> },
    { key: 'progress', label: 'Progress', render: (_: unknown, row: JobRow) => {
      const pct = row.total_items > 0 ? Math.round((row.processed_items / row.total_items) * 100) : 0
      return (
        <div className="flex items-center gap-2 w-28">
          <div className="flex-1 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-[10px] font-mono text-white/40 w-8 text-right">{pct}%</span>
        </div>
      )
    }},
    { key: 'created_at', label: 'Created', render: (v: unknown) => <span className="text-[11px] text-white/30">{formatDateTime(String(v))}</span> },
  ]

  const selectTab = (t: Tab) => {
    router.push(`/admin/chunk-indexing?tab=${t}`)
  }

  // Active reindex jobs (status is queued or processing)
  const activeJobs = jobRows.filter(j => j.status === 'queued' || j.status === 'processing')

  return (
    <div className="space-y-6">
      <PageHeader title="Chunk Indexing Management" description="Inspect and maintain the RAG vector index" />

      <Can
        permission={Permission.CHUNK_VIEW}
        fallback={<EmptyState icon={<Layers className="w-5 h-5" />} title="Your role cannot view chunk indexing status" description="Ask a Super Admin or Platform Owner for access." />}
      >
        <div className="space-y-6">
          {/* Stats Summary */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {[
                { label: 'Total Vectors', value: stats.total_chunks, icon: <Layers className="w-4 h-4" />, color: 'text-blue-400', bg: 'bg-blue-500/10' },
                { label: 'Indexed OK', value: stats.indexed_chunks, icon: <CheckCircle className="w-4 h-4" />, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
                { label: 'Pending Index', value: stats.pending_chunks, icon: <Clock className="w-4 h-4" />, color: 'text-amber-400', bg: 'bg-amber-500/10' },
                { label: 'Failed Index', value: stats.failed_chunks, icon: <AlertCircle className="w-4 h-4" />, color: 'text-red-400', bg: 'bg-red-500/10' },
                { label: 'Stale Vectors', value: stats.stale_chunks, icon: <XCircle className="w-4 h-4" />, color: 'text-white/40', bg: 'bg-white/[0.04]' },
              ].map(s => (
                <div key={s.label} className={`${s.bg} rounded-2xl p-4 flex items-center gap-3 border border-white/[0.05]`}>
                  <div className={s.color}>{s.icon}</div>
                  <div>
                    <p className="text-xl font-bold text-white">{s.value}</p>
                    <p className="text-[11px] text-white/40">{s.label}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {actionError && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{actionError}</div>
          )}

          {/* Sub-tabs Navigation */}
          <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 w-fit mb-2 flex-wrap">
            {[
              { id: 'explorer' as Tab, label: 'Chunk Explorer', icon: Boxes },
              { id: 'status' as Tab, label: 'Index Status', icon: BarChart2 },
              { id: 'reindex' as Tab, label: 'Re-index', icon: RefreshCw },
              { id: 'failed' as Tab, label: 'Failed Chunks', icon: AlertCircle },
              { id: 'stale' as Tab, label: 'Stale Chunks', icon: Clock },
            ].map(t => {
              const Icon = t.icon
              return (
                <button key={t.id} onClick={() => selectTab(t.id)}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                  <Icon className="w-3.5 h-3.5" />{t.label}
                </button>
              )
            })}
          </div>

          {/* Tab contents */}
          {tab === 'status' && (
            <div className="space-y-6">
              <Card>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-white/70">Index Status</h3>
                  <Btn size="sm" variant="ghost" onClick={refreshAll}><RefreshCw className="w-3 h-3 animate-spin" /> Refresh</Btn>
                </div>
                <div className="space-y-4">
                  <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4">
                    <p className="text-xs font-semibold text-white/70 mb-2">Active Reindexing Tasks ({activeJobs.length})</p>
                    {activeJobs.length === 0 ? (
                      <p className="text-xs text-white/35">No active reindexing jobs at the moment.</p>
                    ) : (
                      <DataTable
                        data={activeJobs.map(j => ({ ...j, id: j.job_id }))}
                        columns={jobColumns as Parameters<typeof DataTable>[0]['columns']}
                        loading={false}
                      />
                    )}
                  </div>
                </div>
              </Card>
            </div>
          )}

          {tab === 'reindex' && (
            <div className="space-y-6">
              <Can permission={Permission.CHUNK_REINDEX}>
                <Card>
                  <h3 className="text-sm font-semibold text-white/70 mb-3">Index Maintenance</h3>
                  <div className="flex flex-wrap items-center gap-3">
                    <Btn variant="secondary" size="sm" disabled={busy === 'retry-failed'}
                      onClick={() => runAction('retry-failed', () => chunkIndexingApi.retryFailed())}>
                      <RotateCcw className="w-3.5 h-3.5" /> Retry Failed Chunks
                    </Btn>
                    <Btn variant="secondary" size="sm" disabled={busy === 'remove-stale'}
                      onClick={() => runAction('remove-stale', () => chunkIndexingApi.removeStale())}>
                      <Trash2 className="w-3.5 h-3.5" /> Remove Stale Vectors
                    </Btn>
                    <div className="flex items-center gap-2">
                      <select value={reindexDomainId} onChange={e => setReindexDomainId(e.target.value)}
                        className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50">
                        <option value="">Select a domain…</option>
                        {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                      </select>
                      <Btn variant="secondary" size="sm" disabled={!reindexDomainId || busy === 'reindex-domain'}
                        onClick={() => runAction('reindex-domain', () => chunkIndexingApi.reindexDomain(reindexDomainId))}>
                        <RefreshCw className="w-3.5 h-3.5" /> Re-index Domain
                      </Btn>
                    </div>
                    <Can permission={Permission.CHUNK_REBUILD_INDEX}>
                      <Btn variant="danger" size="sm" onClick={() => setConfirmRebuild(true)}>
                        <HardDrive className="w-3.5 h-3.5" /> Full Index Rebuild
                      </Btn>
                    </Can>
                  </div>
                </Card>
              </Can>

              <Card>
                <h3 className="text-sm font-semibold text-white/70 mb-4">Reindex Job History</h3>
                {jobsError ? (
                  <div className="text-center py-8 text-sm text-red-400">
                    {jobsErrObj instanceof ApiError ? jobsErrObj.message : 'Failed to load jobs'}
                    <button onClick={() => refetchJobs()} className="block mx-auto mt-2 text-xs text-blue-400 hover:underline">Retry</button>
                  </div>
                ) : (
                  <DataTable
                    data={jobRows}
                    columns={jobColumns as Parameters<typeof DataTable>[0]['columns']}
                    loading={jobsLoading}
                    emptyMessage="No reindex jobs yet"
                    onRowClick={(row) => setInspecting(row)}
                  />
                )}
              </Card>
            </div>
          )}

          {(tab === 'explorer' || tab === 'failed' || tab === 'stale') && (
            <Card>
              <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                <h3 className="text-sm font-semibold text-white/70">
                  {tab === 'explorer' && 'Chunk Explorer'}
                  {tab === 'failed' && 'Failed Chunks'}
                  {tab === 'stale' && 'Stale Chunks'}
                </h3>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5">
                    <Search className="w-3.5 h-3.5 text-white/30" />
                    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search chunk text..." className="bg-transparent text-xs text-white/60 placeholder:text-white/25 outline-none w-40" />
                  </div>
                  <input value={documentFilter} onChange={e => setDocumentFilter(e.target.value)} placeholder="document_id"
                    className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5 text-xs text-white/60 placeholder:text-white/25 outline-none w-32" />
                  <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)}
                    className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5 text-xs text-white outline-none">
                    <option value="">All domains</option>
                    {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                  {tab === 'explorer' && (
                    <div className="flex items-center gap-1 bg-white/[0.04] border border-white/[0.08] rounded-xl p-1">
                      {CHUNK_FILTERS.map(f => (
                        <button key={f.id} onClick={() => setStatusFilter(f.id)}
                          className={`px-3 py-1 rounded-lg text-[11px] font-medium transition-all ${statusFilter === f.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                          {f.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <Can permission={Permission.CHUNK_REINDEX}>
                {selected.size > 0 && (
                  <div className="flex items-center justify-between mb-3 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl">
                    <span className="text-xs text-blue-300">{selected.size} chunk(s) selected</span>
                    <Btn variant="primary" size="sm" disabled={busy === 'reindex-selected'}
                      onClick={() => runAction('reindex-selected', () => chunkIndexingApi.reindexChunks(Array.from(selected)))}>
                      <RefreshCw className="w-3.5 h-3.5" /> Re-index Selected
                  </Btn>
                  </div>
                )}
              </Can>

              {chunksError ? (
                <div className="text-center py-8 text-sm text-red-400">
                  {chunksErrObj instanceof ApiError ? chunksErrObj.message : 'Failed to load chunks'}
                  <button onClick={() => refetchChunks()} className="block mx-auto mt-2 text-xs text-blue-400 hover:underline">Retry</button>
                </div>
              ) : (
                <DataTable
                  data={chunkRows}
                  columns={chunkColumns as Parameters<typeof DataTable>[0]['columns']}
                  loading={chunksLoading}
                  emptyMessage="No chunks match these filters"
                />
              )}
            </Card>
          )}
        </div>
      </Can>

      <Modal open={!!inspecting} onClose={() => setInspecting(null)} title={inspecting ? `${inspecting.job_type} · ${inspecting.job_id}` : 'Reindex Job'} maxWidth="max-w-lg">
        {inspecting && <JobDetail job={inspecting} />}
      </Modal>

      <ConfirmDialog
        open={confirmRebuild}
        onClose={() => setConfirmRebuild(false)}
        onConfirm={() => { setConfirmRebuild(false); runAction('rebuild', () => chunkIndexingApi.rebuild()) }}
        title="Rebuild the full vector index?"
        description="This wipes and rebuilds the ENTIRE FAISS index from PostgreSQL for every domain — not just yours. It can take several minutes and runs as a background job. Only platform-wide administrators can do this."
        confirmLabel="Rebuild Everything"
        danger
      />
    </div>
  )
}

function JobDetail({ job }: { job: ReindexJobOut }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-white/40">Job</p>
          <p className="text-xs font-mono text-white/70">{job.job_id}</p>
        </div>
        <StatusBadge status={job.status} size="md" />
      </div>

      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="bg-white/[0.03] rounded-xl p-3">
          <p className="text-lg font-bold text-white">{job.total_items}</p>
          <p className="text-[10px] text-white/40">Total</p>
        </div>
        <div className="bg-white/[0.03] rounded-xl p-3">
          <p className="text-lg font-bold text-emerald-400">{job.processed_items - job.failed_items}</p>
          <p className="text-[10px] text-white/40">Succeeded</p>
        </div>
        <div className="bg-white/[0.03] rounded-xl p-3">
          <p className="text-lg font-bold text-red-400">{job.failed_items}</p>
          <p className="text-[10px] text-white/40">Failed</p>
        </div>
      </div>

      {job.error_message && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{job.error_message}</div>
      )}

      {job.error_log.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold text-white/50 uppercase tracking-wider mb-2">Errors ({job.error_log.length})</p>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {job.error_log.map((e, i) => (
              <div key={i} className="text-[11px] bg-white/[0.03] rounded-lg px-2.5 py-1.5">
                <p className="font-mono text-white/50">{e.ref}</p>
                <p className="text-red-400/80">{e.error}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-white/30">
        Created {formatDateTime(job.created_at)}{job.completed_at ? ` · Completed ${formatDateTime(job.completed_at)}` : ''}
      </p>
    </div>
  )
}
