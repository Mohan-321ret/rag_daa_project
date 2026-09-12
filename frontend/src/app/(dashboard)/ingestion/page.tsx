'use client'
import { useState, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useDropzone } from 'react-dropzone'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, FileText, File, X, CheckCircle, AlertCircle, Clock, Search, Lock } from 'lucide-react'
import { Can, PageHeader, Card, StatusBadge } from '@/components/shared/index'
import { DataTable } from '@/components/shared/DataTable'
import {
  documentsApi, domainsApi, usersApi, authApi, ingestionJobsApi, ApiError,
  type DocumentListItem, type DomainOut, type UserOut,
} from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission, Role, ROLE_RANK } from '@/lib/rbac'

const fileIcons: Record<string, string> = { pdf: '📄', docx: '📝', xlsx: '📊', html: '🌐', txt: '📃', pptx: '📽️' }

// Human-readable label for the pipeline stage currently reported by the job.
const stageLabels: Record<string, string> = {
  upload: 'Uploading', document_loader: 'Reading document', ocr: 'Running OCR',
  text_cleaning: 'Cleaning text', noise_removal: 'Removing noise', language_detection: 'Detecting language',
  chunking: 'Chunking', embedding: 'Generating embeddings', vector_index: 'Indexing vectors',
  postgres_metadata: 'Saving metadata', neo4j: 'Updating knowledge graph',
}

interface UploadFile {
  id: string
  file: File
  progress: number
  status: 'uploading' | 'queued' | 'processing' | 'done' | 'error' | 'cancelled'
  error?: string
  jobId?: string
  currentStage?: string | null
}

type DocRow = DocumentListItem & { id: string }

export default function IngestionPage() {
  const [uploads, setUploads] = useState<UploadFile[]>([])
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()
  const router = useRouter()

  // ── Upload metadata: domain / visibility / permissions ──────────────────────
  const [me, setMe] = useState<UserOut | null>(null)
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [department, setDepartment] = useState('')
  const [domainId, setDomainId] = useState('')
  const [visibility, setVisibility] = useState<'global' | 'domain' | 'restricted'>('domain')
  const [permissions, setPermissions] = useState('private')
  const [restrictedUserIds, setRestrictedUserIds] = useState<string[]>([])
  const [allUsers, setAllUsers] = useState<UserOut[]>([])

  useEffect(() => {
    authApi.me().then(setMe).catch(() => {})
    domainsApi.list().then(r => setDomains(r.domains)).catch(() => {})
  }, [])

  useEffect(() => {
    if (visibility === 'restricted' && allUsers.length === 0) {
      usersApi.list({ limit: 200 }).then(r => setAllUsers(r.users)).catch(() => {})
    }
  }, [visibility, allUsers.length])

  const isDomainUnrestricted = me ? ROLE_RANK[me.role as Role] >= ROLE_RANK[Role.SUPER_ADMIN] : false
  const myDomainIds = new Set((me?.domains ?? []).map(d => d.id))
  const selectableDomains = isDomainUnrestricted ? domains : domains.filter(d => myDomainIds.has(d.id))
  const needsDomain = visibility !== 'global'
  const canUpload = !needsDomain || !!domainId

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list(0, 100),
  })

  const rows: DocRow[] = (data?.documents ?? []).map(d => ({ ...d, id: d.document_id }))

  /**
   * Upload is a genuine background job (Admin Panel: Data Injection
   * Management) — the POST only returns a job_id + status='queued'. The UI
   * must not claim success until polling confirms the job actually reached
   * status='completed'. Uploaders who hold INGESTION_MONITOR (Domain
   * Manager and up) poll the job directly for real per-stage progress;
   * everyone else (Standard Employee/Analyst, who can upload but aren't
   * granted job-monitoring per the RBAC matrix) falls back to watching the
   * document list they already have DOCUMENT_READ access to — still a real
   * confirmation, just coarser-grained.
   */
  const pollJobStatus = (uploadId: string, jobId: string, filename: string) => {
    const viaDocumentList = () => {
      documentsApi.list(0, 50).then(r => {
        const match = r.documents.find(d => d.original_filename === filename)
        if (match?.processing_status === 'indexed') {
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'done', currentStage: null } : u))
          queryClient.invalidateQueries({ queryKey: ['documents'] })
          return
        }
        if (match?.processing_status === 'failed') {
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'error', error: 'Processing failed', currentStage: null } : u))
          return
        }
        setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'processing' } : u))
        setTimeout(viaDocumentList, 2000)
      }).catch(() => setTimeout(viaDocumentList, 3000))
    }

    const viaJob = () => {
      ingestionJobsApi.get(jobId).then(job => {
        if (job.status === 'completed') {
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'done', currentStage: null } : u))
          queryClient.invalidateQueries({ queryKey: ['documents'] })
        } else if (job.status === 'failed') {
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'error', error: job.error_message ?? 'Processing failed', currentStage: null } : u))
        } else if (job.status === 'cancelled') {
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: 'cancelled', currentStage: null } : u))
        } else {
          // Narrowed to 'queued' | 'processing' here; captured as a const so the
          // narrowing survives into the nested .map() closure below (TS does not
          // preserve control-flow narrowing of a captured property across closures).
          const nextStatus = job.status
          const nextStage = job.current_stage
          setUploads(prev => prev.map(u => u.id === uploadId ? { ...u, status: nextStatus, currentStage: nextStage } : u))
          setTimeout(viaJob, 1200)
        }
      }).catch((err) => {
        // No INGESTION_MONITOR (403) -> fall back; any other error -> keep retrying the job endpoint.
        if (err instanceof ApiError && err.status === 403) viaDocumentList()
        else setTimeout(viaJob, 2000)
      })
    }
    viaJob()
  }

  const runUpload = (uf: UploadFile) => {
    documentsApi.uploadWithProgress(uf.file, {
      department: department || undefined,
      domain_id: domainId || undefined,
      visibility,
      permissions,
      restricted_user_ids: visibility === 'restricted' ? restrictedUserIds : undefined,
    }, (pct) => {
      setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, progress: pct } : u))
    }).then((accepted) => {
      setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, progress: 100, status: 'queued', jobId: accepted.job_id } : u))
      pollJobStatus(uf.id, accepted.job_id, uf.file.name)
    }).catch((err) => {
      const message = err instanceof ApiError ? err.message : 'Upload failed'
      setUploads(prev => prev.map(u => u.id === uf.id ? { ...u, status: 'error', error: message } : u))
    })
  }

  const onDrop = useCallback((accepted: File[]) => {
    if (!canUpload) return
    const newFiles: UploadFile[] = accepted.map(f => ({ id: Math.random().toString(36).slice(2), file: f, progress: 0, status: 'uploading' }))
    setUploads(prev => [...newFiles, ...prev])
    newFiles.forEach(runUpload)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canUpload, department, domainId, visibility, permissions, restrictedUserIds])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: !canUpload,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/msword': ['.doc'],
      'text/html': ['.html', '.htm'],
      'text/plain': ['.txt'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
      'application/vnd.ms-powerpoint': ['.ppt'],
      'text/csv': ['.csv'],
      'application/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls', '.xlsx'],
    },
  })

  const filtered = rows.filter(d => {
    if (filter !== 'all') {
      const status = d.processing_status === 'indexed' ? 'completed' : d.processing_status
      if (status !== filter) return false
    }
    if (search && !d.original_filename.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const columns = [
    { key: 'original_filename', label: 'Document', sortable: true, render: (_: unknown, row: DocRow) => (
      <div className="flex items-center gap-2">
        <span className="text-base">{fileIcons[row.document_type] ?? '📄'}</span>
        <div>
          <p className="text-xs font-medium text-gray-900 dark:text-white/80 max-w-[240px] truncate">{row.original_filename}</p>
          <p className="text-[10px] text-gray-400 dark:text-white/30">{row.document_id}</p>
        </div>
      </div>
    )},
    { key: 'document_type', label: 'Type', render: (v: unknown) => <span className="text-[11px] uppercase font-mono text-gray-500 dark:text-white/50">{String(v)}</span> },
    { key: 'processing_status', label: 'Status', render: (v: unknown) => <StatusBadge status={String(v)} /> },
    { key: 'visibility', label: 'Visibility', render: (v: unknown) => (
      <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-white/50">{String(v ?? 'domain')}</span>
    )},
    { key: 'word_count', label: 'Words', sortable: true, render: (v: unknown) => <span className="text-xs text-gray-700 dark:text-white/60">{Number(v).toLocaleString()}</span> },
    { key: 'ocr_used', label: 'OCR', render: (v: unknown) => <span className="text-[11px] text-gray-500 dark:text-white/40">{v ? 'Yes' : 'No'}</span> },
    { key: 'upload_date', label: 'Uploaded', sortable: true, render: (v: unknown) => <span className="text-[11px] text-gray-500 dark:text-white/40">{formatDateTime(String(v))}</span> },
  ]

  const total = rows.length
  const processingCount = rows.filter(d => d.processing_status === 'processing').length
  const completedCount = rows.filter(d => d.processing_status === 'indexed').length
  const failedCount = rows.filter(d => d.processing_status === 'failed').length

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Ingestion" description="Upload and manage enterprise documents across all sources" />

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Uploaded', value: total, icon: <FileText className="w-4 h-4" />, color: 'text-blue-600 dark:text-blue-400' },
          { label: 'Processing', value: processingCount, icon: <Clock className="w-4 h-4" />, color: 'text-amber-600 dark:text-amber-400' },
          { label: 'Completed', value: completedCount, icon: <CheckCircle className="w-4 h-4" />, color: 'text-emerald-600 dark:text-emerald-400' },
          { label: 'Failed', value: failedCount, icon: <AlertCircle className="w-4 h-4" />, color: 'text-red-600 dark:text-red-400' },
        ].map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className="adaptive-card p-4 flex items-center gap-3">
            <div className={`${s.color} opacity-80`}>{s.icon}</div>
            <div>
              <p className="text-xl font-bold text-gray-900 dark:text-white">{s.value}</p>
              <p className="text-[11px] text-gray-500 dark:text-white/40 font-medium">{s.label}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Drop Zone */}
      <Card>
        <Can
          permission={Permission.DOCUMENT_UPLOAD}
          fallback={
            <div className="border-2 border-dashed border-gray-200 dark:border-white/[0.08] rounded-xl p-10 text-center">
              <Upload className="w-10 h-10 text-gray-300 dark:text-white/10 mx-auto mb-3" />
              <p className="text-sm font-medium text-gray-600 dark:text-white/40">Your role cannot upload documents</p>
              <p className="text-xs text-gray-400 dark:text-white/25 mt-1">Ask a Domain Manager or Analyst to ingest this on your behalf.</p>
            </div>
          }
        >
          <div className="space-y-4">
            {/* Domain-aware metadata panel */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="text-[11px] font-medium text-gray-600 dark:text-white/50 mb-1 block">Visibility</label>
                <select value={visibility} onChange={e => setVisibility(e.target.value as typeof visibility)}
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 text-xs text-gray-900 dark:text-white outline-none focus:border-blue-500/50">
                  <option value="global" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Global (everyone)</option>
                  <option value="domain" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Domain (same-domain members)</option>
                  <option value="restricted" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Restricted (explicit grants)</option>
                </select>
              </div>
              <div>
                <label className="text-[11px] font-medium text-gray-600 dark:text-white/50 mb-1 block">
                  Domain {needsDomain && <span className="text-red-500 dark:text-red-400">*</span>}
                </label>
                <select value={domainId} onChange={e => setDomainId(e.target.value)} disabled={visibility === 'global'}
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 text-xs text-gray-900 dark:text-white outline-none focus:border-blue-500/50 disabled:opacity-40">
                  <option value="" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">{visibility === 'global' ? 'Not required' : 'Select a domain…'}</option>
                  {selectableDomains.map(d => <option key={d.id} value={d.id} className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">{d.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[11px] font-medium text-gray-600 dark:text-white/50 mb-1 block">Department</label>
                <input value={department} onChange={e => setDepartment(e.target.value)} placeholder="e.g. Payroll"
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 text-xs text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 outline-none focus:border-blue-500/50" />
              </div>
              <div>
                <label className="text-[11px] font-medium text-gray-600 dark:text-white/50 mb-1 block">Permissions</label>
                <select value={permissions} onChange={e => setPermissions(e.target.value)}
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 text-xs text-gray-900 dark:text-white outline-none focus:border-blue-500/50">
                  <option value="private" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Private</option>
                  <option value="internal" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Internal</option>
                  <option value="public" className="text-gray-900 dark:text-white bg-white dark:bg-slate-900">Public</option>
                </select>
              </div>
            </div>

            {visibility === 'restricted' && (
              <div>
                <label className="text-[11px] font-medium text-gray-600 dark:text-white/50 mb-1.5 flex items-center gap-1.5"><Lock className="w-3 h-3" /> Grant access to</label>
                <div className="flex flex-wrap gap-1.5 p-2.5 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl max-h-28 overflow-y-auto">
                  {allUsers.length === 0 && <span className="text-[11px] text-gray-400 dark:text-white/25">Loading users…</span>}
                  {allUsers.map(u => (
                    <button key={u.id} type="button"
                      onClick={() => setRestrictedUserIds(prev => prev.includes(u.id) ? prev.filter(x => x !== u.id) : [...prev, u.id])}
                      className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all ${restrictedUserIds.includes(u.id) ? 'bg-blue-600 border-blue-500 text-white' : 'bg-gray-100 dark:bg-white/[0.04] border-gray-200 dark:border-white/[0.08] text-gray-600 dark:text-white/50 hover:text-gray-900 dark:hover:text-white/80'}`}>
                      {u.full_name || u.email}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {needsDomain && !domainId && (
              <p className="text-[11px] text-amber-600 dark:text-amber-400 font-medium">Select a domain before uploading — required unless visibility is Global.</p>
            )}

            <div {...getRootProps()} className={`border-2 border-dashed rounded-xl p-10 text-center transition-all ${!canUpload ? 'opacity-50 cursor-not-allowed border-gray-200 dark:border-white/[0.06]' : 'cursor-pointer ' + (isDragActive ? 'border-blue-500 bg-blue-500/10' : 'border-gray-200 dark:border-white/[0.08] hover:border-gray-300 dark:hover:border-white/20 hover:bg-gray-50 dark:hover:bg-white/[0.02]')}`}>
              <input {...getInputProps()} />
              <motion.div animate={isDragActive ? { scale: 1.05 } : { scale: 1 }}>
                <Upload className="w-10 h-10 text-gray-400 dark:text-white/20 mx-auto mb-3" />
                <p className="text-sm font-medium text-gray-700 dark:text-white/60">{isDragActive ? 'Drop files here...' : 'Drag & drop files or click to browse'}</p>
                <p className="text-xs text-gray-400 dark:text-white/30 mt-1">Supports PDF, DOCX, HTML, TXT, PPTX</p>
                <div className="flex items-center justify-center gap-2 mt-4">
                  {['PDF', 'DOCX', 'HTML', 'TXT', 'PPTX'].map(t => (
                    <span key={t} className="text-[10px] bg-gray-100 dark:bg-white/[0.06] text-gray-500 dark:text-white/40 px-2 py-1 rounded-lg font-mono">{t}</span>
                  ))}
                </div>
              </motion.div>
            </div>
          </div>
        </Can>

        {/* Active Uploads */}
        <AnimatePresence>
          {uploads.length > 0 && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="mt-4 space-y-2">
              {uploads.map(u => (
                <motion.div key={u.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }}
                  className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-white/[0.03] rounded-xl border border-gray-200 dark:border-white/[0.05]">
                  <File className="w-4 h-4 text-gray-400 dark:text-white/40 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-800 dark:text-white/70 truncate">{u.file.name}</p>
                      <div className="flex items-center gap-2">
                        {u.status === 'done' && <CheckCircle className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" />}
                        {u.status === 'error' && <span className="text-[10px] text-red-500 dark:text-red-400" title={u.error}><AlertCircle className="w-3.5 h-3.5 inline" /> {u.error}</span>}
                        {u.status === 'cancelled' && <span className="text-[10px] text-gray-400 dark:text-white/40">Cancelled</span>}
                        {u.status === 'uploading' && <span className="text-[10px] text-blue-600 dark:text-blue-400">{Math.round(u.progress)}%</span>}
                        {u.status === 'queued' && <span className="text-[10px] text-amber-600 dark:text-amber-400">Queued…</span>}
                        {u.status === 'processing' && (
                          <span className="text-[10px] text-blue-600 dark:text-blue-400">{u.currentStage ? (stageLabels[u.currentStage] ?? u.currentStage) : 'Processing…'}</span>
                        )}
                        <button onClick={() => setUploads(p => p.filter(x => x.id !== u.id))} className="text-gray-400 dark:text-white/20 hover:text-gray-600 dark:hover:text-white/50"><X className="w-3 h-3" /></button>
                      </div>
                    </div>
                    <div className="h-1 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden">
                      <motion.div
                        animate={{ width: u.status === 'uploading' ? `${u.progress}%` : '100%' }}
                        className={`h-full rounded-full ${
                          u.status === 'done' ? 'bg-emerald-500'
                          : u.status === 'error' ? 'bg-red-500'
                          : u.status === 'cancelled' ? 'bg-gray-300 dark:bg-white/20'
                          : u.status === 'queued' ? 'bg-amber-500'
                          : 'bg-gradient-to-r from-blue-500 to-violet-500 animate-pulse'
                        }`}
                      />
                    </div>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {/* Documents Table */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70">Documents</h3>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-1.5">
              <Search className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search documents..." className="bg-transparent text-xs text-gray-800 dark:text-white/60 placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none w-40" />
            </div>
            <div className="flex items-center gap-1 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl p-1">
              {['all', 'completed', 'processing', 'failed'].map(f => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium capitalize transition-all ${filter === f ? 'bg-blue-600 text-white' : 'text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/70'}`}>
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>
        {isError ? (
          <div className="text-center py-8 text-sm text-red-500 dark:text-red-400">
            {error instanceof ApiError ? error.message : 'Failed to load documents'}
            <button onClick={() => refetch()} className="block mx-auto mt-2 text-xs text-blue-600 dark:text-blue-400 hover:underline">Retry</button>
          </div>
        ) : (
          <DataTable
            data={filtered}
            columns={columns as Parameters<typeof DataTable>[0]['columns']}
            loading={isLoading}
            emptyMessage="No documents uploaded yet"
            onRowClick={(row) => router.push(`/documents?id=${row.id}`)}
          />
        )}
      </Card>
    </div>
  )
}
