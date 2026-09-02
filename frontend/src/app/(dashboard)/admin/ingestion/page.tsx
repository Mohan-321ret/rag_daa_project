'use client'
import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useRouter } from 'next/navigation'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FileText, Clock, CheckCircle, AlertCircle, XCircle, Loader2,
  RotateCcw, Ban, Eye, Layers, Upload, X, Globe2, Activity,
  Briefcase, RefreshCw,
} from 'lucide-react'
import { Can, PageHeader, Card, StatusBadge, Modal, Btn, EmptyState } from '@/components/shared/index'
import { DataTable } from '@/components/shared/DataTable'
import {
  ingestionJobsApi, documentsApi, domainsApi, ApiError, INGESTION_PIPELINE_STAGES,
  type IngestionJobOut, type IngestionJobStatus, type DomainOut
} from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission } from '@/lib/rbac'

const stageLabels: Record<string, string> = {
  upload: 'Upload', document_loader: 'Document Loader', ocr: 'OCR',
  text_cleaning: 'Text Cleaning', noise_removal: 'Noise Removal', language_detection: 'Language Detection',
  chunking: 'Chunking', embedding: 'Embedding', vector_index: 'Vector Index',
  postgres_metadata: 'PostgreSQL Metadata', neo4j: 'Neo4j',
}

interface UploadFile {
  id: string
  file: File
  progress: number
  status: 'uploading' | 'queued' | 'processing' | 'done' | 'error'
  error?: string
  jobId?: string
}

type JobRow = IngestionJobOut & { id: string }

type Tab = 'upload' | 'jobs' | 'status' | 'failed' | 'retry'

const FILTERS: { id: IngestionJobStatus | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'queued', label: 'Queued' },
  { id: 'processing', label: 'Processing' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
]

export default function DataInjectionDashboardPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null
  
  const [tab, setTab] = useState<Tab>('jobs')
  const [filter, setFilter] = useState<IngestionJobStatus | 'all'>('all')
  const [inspecting, setInspecting] = useState<IngestionJobOut | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [uploads, setUploads] = useState<UploadFile[]>([])
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [selectedDomainId, setSelectedDomainId] = useState('')
  const queryClient = useQueryClient()

  // Load domains for uploading
  useEffect(() => {
    domainsApi.list().then(r => setDomains(r.domains)).catch(() => {})
  }, [])

  // Sync tab with search parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
      if (tabParam === 'jobs') setFilter('all')
      else if (tabParam === 'status') setFilter('processing') // processing/queued
      else if (tabParam === 'failed') setFilter('failed')
      else if (tabParam === 'retry') setFilter('failed')
    } else {
      setTab('upload')
    }
  }, [tabParam])

  const isJobActive = (j?: IngestionJobOut) => j?.status === 'queued' || j?.status === 'processing'

  const { data: stats } = useQuery({
    queryKey: ['ingestion-stats'],
    queryFn: () => ingestionJobsApi.stats(),
    refetchInterval: 5000,
  })

  // We load jobs depending on active tab status
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['ingestion-jobs', filter, tab],
    queryFn: () => {
      let statusQuery: IngestionJobStatus | undefined = filter === 'all' ? undefined : filter
      if (tab === 'status') {
        statusQuery = undefined
      }
      return ingestionJobsApi.list({ status: statusQuery, limit: 100 })
    },
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? []
      return jobs.some(isJobActive) ? 3000 : 8000
    },
  })

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['ingestion-jobs'] })
    queryClient.invalidateQueries({ queryKey: ['ingestion-stats'] })
  }

  const runAction = async (jobId: string, action: 'retry' | 'cancel') => {
    setBusyJobId(jobId)
    setActionError(null)
    try {
      await (action === 'retry' ? ingestionJobsApi.retry(jobId) : ingestionJobsApi.cancel(jobId))
      refreshAll()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : `Failed to ${action} job`)
    } finally {
      setBusyJobId(null)
    }
  }

  // ── Drag & Drop File Upload Handlers ──────────────────────────────────────
  const runUpload = (uf: UploadFile) => {
    documentsApi.uploadWithProgress(
      uf.file,
      {
        domain_id: selectedDomainId || undefined,
        visibility: selectedDomainId ? 'domain' : 'global',
        permissions: 'public',
      },
      (pct) => {
        setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, progress: pct } : u))
      }
    ).then((accepted) => {
      setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, progress: 100, status: 'queued', jobId: accepted.job_id } : u))
      refreshAll()
    }).catch((err) => {
      const message = err instanceof ApiError ? err.message : 'Upload failed'
      setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, status: 'error', error: message } : u))
    })
  }

  const onDrop = useCallback((accepted: File[]) => {
    const newFiles: UploadFile[] = accepted.map(f => ({
      id: Math.random().toString(36).slice(2),
      file: f,
      progress: 0,
      status: 'uploading'
    }))
    setUploads(prev => [...newFiles, ...prev])
    newFiles.forEach(runUpload)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDomainId])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/html': ['.html'],
      'text/plain': ['.txt'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
    },
  })

  // Filter jobs based on active tab requirements
  let displayedJobs = data?.jobs ?? []
  if (tab === 'status') {
    displayedJobs = displayedJobs.filter(j => j.status === 'processing' || j.status === 'queued')
  } else if (tab === 'failed' || tab === 'retry') {
    displayedJobs = displayedJobs.filter(j => j.status === 'failed')
  } else if (filter !== 'all') {
    displayedJobs = displayedJobs.filter(j => j.status === filter)
  }

  const rows: JobRow[] = displayedJobs.map(j => ({ ...j, id: j.job_id }))

  const columns = [
    { key: 'original_filename', label: 'Document', render: (_: unknown, row: JobRow) => (
      <div>
        <p className="text-xs font-medium text-white/80 max-w-[220px] truncate">{row.original_filename}</p>
        <p className="text-[10px] text-white/30">{row.job_id}{row.document_id ? ` · ${row.document_id}` : ''}</p>
      </div>
    )},
    { key: 'status', label: 'Status', render: (v: unknown, row: JobRow) => (
      <div className="flex items-center gap-1.5">
        <StatusBadge status={String(v)} />
        {row.status === 'processing' && row.current_stage && (
          <span className="text-[10px] text-white/40">{stageLabels[row.current_stage] ?? row.current_stage}</span>
        )}
      </div>
    )},
    { key: 'action', label: 'Type', render: (v: unknown) => (
      <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-white/[0.06] text-white/50">{v ? String(v) : '—'}</span>
    )},
    { key: 'retry_count', label: 'Retries', render: (v: unknown) => <span className="text-xs text-white/60">{Number(v)}</span> },
    { key: 'created_at', label: 'Created', sortable: true, render: (v: unknown) => <span className="text-[11px] text-white/40">{formatDateTime(String(v))}</span> },
    { key: 'actions', label: '', render: (_: unknown, row: JobRow) => (
      <div className="flex items-center justify-end gap-1.5" onClick={e => e.stopPropagation()}>
        <button onClick={() => setInspecting(row)} title="Inspect" className="p-1.5 rounded-lg text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
          <Eye className="w-3.5 h-3.5" />
        </button>
        <Can permission={Permission.INGESTION_RETRY}>
          <>
            {row.status === 'failed' && (
              <button
                onClick={() => runAction(row.job_id, 'retry')}
                disabled={!row.document_id || busyJobId === row.job_id}
                title={row.document_id ? 'Retry' : 'No extracted text saved — re-upload instead'}
                className="p-1.5 rounded-lg text-blue-400/70 hover:text-blue-400 hover:bg-blue-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                {busyJobId === row.job_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
              </button>
            )}
            {row.status === 'queued' && (
              <button
                onClick={() => runAction(row.job_id, 'cancel')}
                disabled={busyJobId === row.job_id}
                title="Cancel"
                className="p-1.5 rounded-lg text-red-400/70 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30 transition-colors"
              >
                {busyJobId === row.job_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
              </button>
            )}
          </>
        </Can>
      </div>
    )},
  ]

  const cards = [
    { label: 'Total Documents', value: stats?.total_documents ?? 0, icon: <FileText className="w-4 h-4" />, color: 'text-blue-400' },
    { label: 'Queued', value: stats?.queued ?? 0, icon: <Clock className="w-4 h-4" />, color: 'text-amber-400' },
    { label: 'Processing', value: stats?.processing ?? 0, icon: <Loader2 className="w-4 h-4" />, color: 'text-blue-400' },
    { label: 'Completed', value: stats?.completed ?? 0, icon: <CheckCircle className="w-4 h-4" />, color: 'text-emerald-400' },
    { label: 'Failed', value: stats?.failed ?? 0, icon: <AlertCircle className="w-4 h-4" />, color: 'text-red-400' },
    { label: 'Cancelled', value: stats?.cancelled ?? 0, icon: <XCircle className="w-4 h-4" />, color: 'text-white/40' },
  ]

  const selectTab = (t: Tab) => {
    router.push(`/admin/ingestion?tab=${t}`)
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Data Injection Management" description="Monitor and feed the enterprise knowledge ingestion pipeline" />

      <Can
        permission={Permission.INGESTION_MONITOR}
        fallback={<EmptyState icon={<Layers className="w-5 h-5" />} title="Your role cannot monitor ingestion jobs" description="Ask a Domain Manager or Administrator for access." />}
      >
        <div className="space-y-6">
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
            {cards.map((s, i) => (
              <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
                className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-4">
                <div className={`${s.color} opacity-70 mb-2`}>{s.icon}</div>
                <p className="text-xl font-bold text-white">{s.value}</p>
                <p className="text-[11px] text-white/40">{s.label}</p>
              </motion.div>
            ))}
          </div>
          {stats?.last_ingestion_at && (
            <p className="text-[11px] text-white/30 -mt-3">Last completed ingestion: {formatDateTime(stats.last_ingestion_at)}</p>
          )}

          {actionError && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{actionError}</div>
          )}

          {/* Sub-tabs Navigation */}
          <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 w-fit mb-2 flex-wrap">
            {[
              { id: 'upload' as Tab, label: 'Upload File', icon: Upload },
              { id: 'jobs' as Tab, label: 'Ingestion Jobs', icon: Briefcase },
              { id: 'status' as Tab, label: 'Processing Status', icon: Activity },
              { id: 'failed' as Tab, label: 'Failed Jobs', icon: AlertCircle },
              { id: 'retry' as Tab, label: 'Retry Jobs', icon: RefreshCw },
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

          {tab === 'upload' ? (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 space-y-4">
                <Card>
                  <h3 className="text-sm font-semibold text-white/70 mb-4">Upload Document</h3>
                  <div className="space-y-4">
                    {/* Domain assignment selection */}
                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-white/50 uppercase tracking-wider">Assign to Domain (Optional)</label>
                      <div className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-white">
                        <Globe2 className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                        <select
                          value={selectedDomainId}
                          onChange={e => setSelectedDomainId(e.target.value)}
                          className="w-full bg-transparent border-none text-xs text-white outline-none"
                        >
                          <option value="" className="bg-[#0e0e16]">Global / Platform (No Specific Domain)</option>
                          {domains.map(d => (
                            <option key={d.id} value={d.id} className="bg-[#0e0e16]">{d.name}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    {/* Drag and Drop Zone */}
                    <div
                      {...getRootProps()}
                      className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ${
                        isDragActive
                          ? 'border-blue-500 bg-blue-500/5'
                          : 'border-white/10 hover:border-white/20 hover:bg-white/[0.01]'
                      }`}
                    >
                      <input {...getInputProps()} />
                      <Upload className="w-8 h-8 text-blue-400 mx-auto mb-3" />
                      <p className="text-sm text-white/80 font-medium">Drag & drop files here, or click to browse</p>
                      <p className="text-xs text-white/30 mt-1.5">Supports PDF, DOCX, HTML, TXT, PPTX (max 50MB)</p>
                    </div>
                  </div>
                </Card>

                {/* Upload status feed */}
                <AnimatePresence>
                  {uploads.length > 0 && (
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-xs font-semibold text-white/70">Uploaded Queue ({uploads.length})</h4>
                        <button onClick={() => setUploads([])} className="text-[10px] text-white/40 hover:text-white/60">Clear Queue</button>
                      </div>
                      <div className="space-y-2.5">
                        {uploads.map(u => (
                          <div key={u.id} className="flex items-center gap-3 bg-white/[0.02] border border-white/[0.06] rounded-xl p-3">
                            <FileText className="w-4 h-4 text-blue-400" />
                            <div className="flex-1 min-w-0">
                              <p className="text-xs text-white/70 truncate">{u.file.name}</p>
                              {u.status === 'uploading' && (
                                <div className="w-full bg-white/[0.08] h-1 rounded-full mt-1.5 overflow-hidden">
                                  <div className="bg-blue-500 h-full rounded-full transition-all duration-150" style={{ width: `${u.progress}%` }} />
                                </div>
                              )}
                              {u.status === 'queued' && <p className="text-[10px] text-amber-400 mt-1">Queued (Job ID: {u.jobId})</p>}
                              {u.status === 'error' && <p className="text-[10px] text-red-400 mt-1">{u.error}</p>}
                            </div>
                            <div className="flex-shrink-0">
                              {u.status === 'done' && <CheckCircle className="w-4 h-4 text-emerald-400" />}
                              {u.status === 'error' && <XCircle className="w-4 h-4 text-red-400" />}
                              {u.status === 'uploading' && <span className="text-[10px] font-mono text-white/40">{u.progress}%</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </Card>
                  )}
                </AnimatePresence>
              </div>

              {/* Ingestion Pipeline Reference */}
              <div className="lg:col-span-1">
                <Card>
                  <h3 className="text-sm font-semibold text-white/70 mb-3">Ingestion Pipeline</h3>
                  <p className="text-xs text-white/40 mb-4">Every document goes through these stages sequentially:</p>
                  <div className="space-y-3">
                    {INGESTION_PIPELINE_STAGES.map((stage, i) => (
                      <div key={stage} className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-[10px] font-mono text-white/40 flex-shrink-0">{i + 1}</span>
                        <span className="text-xs text-white/70">{stageLabels[stage] ?? stage}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          ) : (
            <Card>
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <h3 className="text-sm font-semibold text-white/70">
                  {tab === 'jobs' && 'Ingestion Jobs'}
                  {tab === 'status' && 'Processing Status (Active)'}
                  {tab === 'failed' && 'Failed Ingestion Jobs'}
                  {tab === 'retry' && 'Failed Jobs Available for Retry'}
                </h3>
                {tab === 'jobs' && (
                  <div className="flex items-center gap-1 bg-white/[0.04] border border-white/[0.08] rounded-xl p-1">
                    {FILTERS.map(f => (
                      <button key={f.id} onClick={() => setFilter(f.id)}
                        className={`px-3 py-1 rounded-lg text-[11px] font-medium transition-all ${filter === f.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                        {f.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {isError ? (
                <div className="text-center py-8 text-sm text-red-400">
                  {error instanceof ApiError ? error.message : 'Failed to load ingestion jobs'}
                  <button onClick={() => refetch()} className="block mx-auto mt-2 text-xs text-blue-400 hover:underline">Retry</button>
                </div>
              ) : (
                <DataTable
                  data={rows}
                  columns={columns as Parameters<typeof DataTable>[0]['columns']}
                  loading={isLoading}
                  emptyMessage="No ingestion jobs match this filter"
                  onRowClick={(row) => setInspecting(row)}
                />
              )}
            </Card>
          )}
        </div>
      </Can>

      <Modal open={!!inspecting} onClose={() => setInspecting(null)} title={inspecting?.original_filename ?? 'Ingestion Job'} maxWidth="max-w-lg">
        {inspecting && <JobDetail job={inspecting} />}
      </Modal>
    </div>
  )
}

function JobDetail({ job }: { job: IngestionJobOut }) {
  const byStage = new Map(job.stage_log.map(e => [e.stage, e]))
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-white/40">Job</p>
          <p className="text-xs font-mono text-white/70">{job.job_id}</p>
        </div>
        <StatusBadge status={job.status} size="md" />
      </div>

      {job.document_id && (
        <div>
          <p className="text-xs text-white/40">Document</p>
          <p className="text-xs font-mono text-white/70">{job.document_id}{job.action ? ` (${job.action})` : ''}</p>
        </div>
      )}

      {job.retry_of_job_id && (
        <p className="text-[11px] text-white/40">Retry #{job.retry_count} of <span className="font-mono">{job.retry_of_job_id}</span></p>
      )}

      {job.error_message && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{job.error_message}</div>
      )}

      <div>
        <p className="text-[11px] font-semibold text-white/50 uppercase tracking-wider mb-2">Pipeline Progress</p>
        <div className="space-y-1.5">
          {INGESTION_PIPELINE_STAGES.map(stage => {
            const entry = byStage.get(stage)
            const status = entry?.status ?? 'pending'
            const dot = status === 'completed' ? 'bg-emerald-500' : status === 'failed' ? 'bg-red-500'
              : status === 'running' ? 'bg-blue-500 animate-pulse' : status === 'skipped' ? 'bg-gray-500' : 'bg-white/10'
            return (
              <div key={stage} className="flex items-center gap-2.5">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
                <span className="text-xs text-white/60 flex-1">{stageLabels[stage] ?? stage}</span>
                <span className="text-[10px] text-white/30 capitalize">{status}</span>
              </div>
            )
          })}
        </div>
      </div>

      <div>
        <p className="text-[11px] text-white/30">Created {formatDateTime(job.created_at)}{job.completed_at ? ` · Completed ${formatDateTime(job.completed_at)}` : ''}</p>
      </div>
    </div>
  )
}
