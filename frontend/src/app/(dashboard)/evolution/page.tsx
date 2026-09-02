'use client'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  GitBranch, AlertTriangle, Play, Square, RefreshCw, CheckCircle2,
  XCircle, ArrowRight, ShieldCheck, Sparkles, Layers, FileText, Check,
} from 'lucide-react'
import { PageHeader, Card, StatusBadge, EmptyState, Modal, Btn, Can } from '@/components/shared/index'
import {
  evolutionApi,
  knowledgeUpdatesApi,
  ApiError,
  type ChangeEventSummary,
  type ChangeEventDetail,
  type KnowledgeUpdateRequest,
  type KnowledgeUpdateStatsResponse,
  RESOLUTION_TYPE_LABELS,
  type ResolutionType,
} from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission } from '@/lib/rbac'

type CombinedEvent = ChangeEventSummary & Partial<Omit<ChangeEventDetail, keyof ChangeEventSummary>>

export default function EvolutionPage() {
  const [activeTab, setActiveTab] = useState<'timeline' | 'recommendations'>('timeline')
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  // ── Tab 1: Evolution Timeline Data ──────────────────────────────────────────
  const { data: changes, isLoading: timelineLoading, isError: timelineIsError, error: timelineError } = useQuery({
    queryKey: ['evolution-changes'],
    queryFn: () => evolutionApi.changes({ limit: 50 }),
  })

  const { data: watcher } = useQuery({
    queryKey: ['evolution-watcher'],
    queryFn: () => evolutionApi.watcherStatus(),
    refetchInterval: 15000,
  })

  const { data: detail } = useQuery({
    queryKey: ['evolution-change-detail', selectedEventId],
    queryFn: () => evolutionApi.changeDetail(selectedEventId as string),
    enabled: !!selectedEventId,
  })

  const events = changes?.events ?? []
  const selected: CombinedEvent | undefined = detail ?? events.find(e => e.event_id === selectedEventId) ?? events[0]

  const toggleWatcher = async () => {
    if (watcher?.running) await evolutionApi.watcherStop()
    else await evolutionApi.watcherStart()
    queryClient.invalidateQueries({ queryKey: ['evolution-watcher'] })
  }

  const statusFor = (changeType: string) => changeType === 'new_document' ? 'completed' : changeType === 'new_version' ? 'current' : 'stable'

  // ── Tab 2: Ticket Update Requests (Phase 14) ────────────────────────────────
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [reviewModalReq, setReviewModalReq] = useState<KnowledgeUpdateRequest | null>(null)
  const [reviewAction, setReviewAction] = useState<'approve' | 'reject'>('approve')
  const [adminNotes, setAdminNotes] = useState('')
  const [reviewing, setReviewing] = useState(false)

  const [applyModalReq, setApplyModalReq] = useState<KnowledgeUpdateRequest | null>(null)
  const [applyText, setApplyText] = useState('')
  const [applyFilename, setApplyFilename] = useState('')
  const [applying, setApplying] = useState(false)
  const [applySuccessMsg, setApplySuccessMsg] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: updateRequestsData, isLoading: reqsLoading, refetch: refetchReqs } = useQuery({
    queryKey: ['knowledge-update-requests', statusFilter],
    queryFn: () => knowledgeUpdatesApi.list({ status: statusFilter === 'all' ? undefined : statusFilter, limit: 50 }),
  })

  const { data: updateStats, refetch: refetchStats } = useQuery({
    queryKey: ['knowledge-update-stats'],
    queryFn: () => knowledgeUpdatesApi.stats(),
  })

  const requests = updateRequestsData?.requests ?? []

  const handleOpenReview = (req: KnowledgeUpdateRequest, action: 'approve' | 'reject') => {
    setReviewModalReq(req)
    setReviewAction(action)
    setAdminNotes('')
    setActionError(null)
  }

  const handleExecuteReview = async () => {
    if (!reviewModalReq) return
    setReviewing(true)
    setActionError(null)
    try {
      await knowledgeUpdatesApi.review(reviewModalReq.request_id, {
        action: reviewAction,
        admin_notes: adminNotes.trim() || undefined,
      })
      setReviewModalReq(null)
      refetchReqs()
      refetchStats()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to submit review.')
    } finally {
      setReviewing(false)
    }
  }

  const handleOpenApply = (req: KnowledgeUpdateRequest) => {
    setApplyModalReq(req)
    setApplyText(req.suggested_resolution || '')
    setApplyFilename(req.target_filename || (req.domain ? `${req.domain}_policy.txt` : 'knowledge_update.txt'))
    setActionError(null)
    setApplySuccessMsg(null)
  }

  const handleExecuteApply = async () => {
    if (!applyModalReq || !applyText.trim()) {
      setActionError('Authoritative text content is required.')
      return
    }
    setApplying(true)
    setActionError(null)
    setApplySuccessMsg(null)
    try {
      const res = await knowledgeUpdatesApi.apply(applyModalReq.request_id, {
        updated_text: applyText.trim(),
        target_filename: applyFilename.trim() || undefined,
        admin_notes: `Applied by admin with ${applyText.length} characters.`,
      })
      setApplySuccessMsg(
        `Update applied successfully! Created Document ${res.evolution_result.document_id} (Version ${res.evolution_result.version}) & Event ${res.evolution_result.event_id}. Incremental FAISS reindexing complete.`
      )
      refetchReqs()
      refetchStats()
      queryClient.invalidateQueries({ queryKey: ['evolution-changes'] })
      setTimeout(() => {
        setApplyModalReq(null)
        setApplySuccessMsg(null)
      }, 2500)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Failed to execute knowledge update.')
    } finally {
      setApplying(false)
    }
  }

  const getStatusBadge = (st: string) => {
    switch (st) {
      case 'pending_review':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/25">Pending Review</span>
      case 'approved':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500/15 text-blue-400 border border-blue-500/25">Approved</span>
      case 'applied':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">Applied (v2+)</span>
      case 'rejected':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-red-500/15 text-red-400 border border-red-500/25">Rejected</span>
      default:
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-gray-500/15 text-gray-400 border border-gray-500/25">{st}</span>
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Knowledge Evolution Engine"
        description="Phase 6 & 14: Automated Version Comparison, Concept Drift, Conflict Detection, and Ticket-Driven Governance Recommendations."
      >
        <button onClick={toggleWatcher} className={`flex items-center gap-2 px-4 py-2 rounded-xl border text-xs font-semibold transition-all ${watcher?.running ? 'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'}`}>
          {watcher?.running ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          {watcher?.running ? 'Stop Watcher' : 'Start Watcher'}
        </button>
      </PageHeader>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-white/[0.08] pb-1">
        <button
          onClick={() => setActiveTab('timeline')}
          className={`px-4 py-2 text-xs font-semibold rounded-t-xl transition-all border-b-2 flex items-center gap-2 ${
            activeTab === 'timeline'
              ? 'border-blue-500 text-blue-400 bg-white/[0.02]'
              : 'border-transparent text-white/50 hover:text-white/80'
          }`}
        >
          <GitBranch className="w-3.5 h-3.5" /> Evolution Timeline & Diff
        </button>
        <button
          onClick={() => setActiveTab('recommendations')}
          className={`px-4 py-2 text-xs font-semibold rounded-t-xl transition-all border-b-2 flex items-center gap-2 ${
            activeTab === 'recommendations'
              ? 'border-blue-500 text-blue-400 bg-white/[0.02]'
              : 'border-transparent text-white/50 hover:text-white/80'
          }`}
        >
          <ShieldCheck className="w-3.5 h-3.5" /> Ticket Update Recommendations (Phase 14)
          {updateStats && updateStats.pending_review > 0 && (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-amber-500/20 text-amber-300 font-bold">
              {updateStats.pending_review}
            </span>
          )}
        </button>
      </div>

      {activeTab === 'timeline' ? (
        <>
          {/* Watcher status */}
          <Card>
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <div className={`w-2.5 h-2.5 rounded-full ${watcher?.running ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500'}`} />
                <div>
                  <p className="text-sm font-semibold text-white">Folder Watcher {watcher?.running ? 'Running' : 'Stopped'}</p>
                  <p className="text-xs text-white/40">{watcher?.watch_dir ?? '—'} · polling every {watcher?.poll_interval_s ?? '—'}s</p>
                </div>
              </div>
              <div className="flex items-center gap-6 text-xs text-white/50">
                <span>Tracked: <strong className="text-white/80">{watcher?.files_tracked ?? 0}</strong></span>
                <span>Ingested: <strong className="text-white/80">{watcher?.files_ingested ?? 0}</strong></span>
                <span>Last scan: {watcher?.last_scan ? formatDateTime(watcher.last_scan) : '—'}</span>
              </div>
            </div>
          </Card>

          {timelineIsError && (
            <Card><p className="text-sm text-red-400 text-center py-4">{timelineError instanceof ApiError ? timelineError.message : 'Failed to load evolution timeline'}</p></Card>
          )}

          {!timelineIsError && !timelineLoading && events.length === 0 && (
            <Card><EmptyState icon={<GitBranch className="w-5 h-5" />} title="No evolution events yet" description="Upload a document or apply a ticket update recommendation to see evolution diffs here." /></Card>
          )}

          {events.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Timeline */}
              <Card className="lg:col-span-1">
                <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-4">Change Timeline</h3>
                <div className="space-y-1 max-h-[600px] overflow-y-auto">
                  {events.map((e, i) => (
                    <motion.button key={e.event_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}
                      onClick={() => setSelectedEventId(e.event_id)}
                      className={`w-full flex items-start gap-3 p-3 rounded-xl text-left transition-all ${selected?.event_id === e.event_id ? 'bg-blue-600/15 border border-blue-500/20' : 'hover:bg-white/[0.03]'}`}>
                      <div className="relative mt-1">
                        <div className={`w-2.5 h-2.5 rounded-full ${e.drift_detected ? 'bg-amber-400' : 'bg-blue-400'}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-bold text-white/80 truncate">{e.filename}</span>
                          <StatusBadge status={statusFor(e.change_type)} />
                        </div>
                        <p className="text-[10px] text-white/40 mt-0.5">{formatDateTime(e.detected_at)}</p>
                        <p className="text-[11px] text-white/50 mt-1 capitalize">{e.change_type.replace(/_/g, ' ')}{e.conflict_count > 0 ? ` · ${e.conflict_count} conflicts` : ''}</p>
                      </div>
                    </motion.button>
                  ))}
                </div>
              </Card>

              {/* Detail */}
              <div className="lg:col-span-2 space-y-4">
                {selected && (
                  <>
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <div>
                          <h3 className="text-sm font-bold text-white">{selected.filename}</h3>
                          <p className="text-xs text-white/40 mt-0.5">{formatDateTime(selected.detected_at)} · source: {selected.source}</p>
                        </div>
                        <StatusBadge status={statusFor(selected.change_type)} size="md" />
                      </div>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Chunks Added', value: selected.chunks_added },
                          { label: 'Chunks Removed', value: selected.chunks_removed },
                          { label: 'Chunks Unchanged', value: selected.chunks_unchanged },
                        ].map(s => (
                          <div key={s.label} className="bg-white/[0.03] rounded-xl p-3 text-center">
                            <p className="text-lg font-bold text-white">{s.value}</p>
                            <p className="text-[10px] text-white/30">{s.label}</p>
                          </div>
                        ))}
                      </div>
                      {(selected.text_similarity != null || selected.embedding_similarity != null) && (
                        <div className="mt-3 flex items-center gap-4 text-xs text-white/50">
                          {selected.text_similarity != null && <span>Text similarity: <strong className="text-white/80">{(selected.text_similarity * 100).toFixed(1)}%</strong></span>}
                          {selected.embedding_similarity != null && <span>Embedding similarity: <strong className="text-white/80">{(selected.embedding_similarity * 100).toFixed(1)}%</strong></span>}
                        </div>
                      )}
                    </Card>

                    {selected.unified_diff && (
                      <Card>
                        <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Unified Diff</h3>
                        <div className="bg-[#0a0a14] rounded-xl p-4 font-mono text-[11px] text-white/60 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
                          {selected.unified_diff}
                        </div>
                      </Card>
                    )}

                    {selected.conflicts && selected.conflicts.length > 0 && (() => {
                      const conflicts = selected.conflicts!
                      return (
                        <Card>
                          <div className="flex items-center gap-2 mb-4">
                            <AlertTriangle className="w-4 h-4 text-amber-400" />
                            <h3 className="text-xs font-semibold text-white/70">Detected Conflicts</h3>
                            <span className="ml-auto text-[10px] bg-amber-400/10 text-amber-400 px-2 py-0.5 rounded-full">{conflicts.length}</span>
                          </div>
                          <div className="space-y-2">
                            {conflicts.map((c, i) => (
                              <pre key={i} className="p-3 rounded-xl border border-amber-500/20 bg-amber-500/5 text-[11px] text-white/60 overflow-x-auto">{JSON.stringify(c, null, 2)}</pre>
                            ))}
                          </div>
                        </Card>
                      )
                    })()}
                  </>
                )}
              </div>
            </div>
          )}
        </>
      ) : (
        /* ── Tab 2: Ticket Update Recommendations (Phase 14) ──────────────────── */
        <div className="space-y-4">
          {/* Governance Stats */}
          {updateStats && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {[
                { label: 'Pending Review', value: updateStats.pending_review, color: 'text-amber-400' },
                { label: 'Approved (Ready to Apply)', value: updateStats.approved, color: 'text-blue-400' },
                { label: 'Applied (v2+ Reindexed)', value: updateStats.applied, color: 'text-emerald-400' },
                { label: 'Rejected', value: updateStats.rejected, color: 'text-rose-400' },
                { label: 'Total Staged', value: updateStats.total, color: 'text-white/80' },
              ].map(s => (
                <div key={s.label} className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-4">
                  <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                  <p className="text-[11px] text-white/40 mt-1">{s.label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Filters */}
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1">
              {(['all', 'pending_review', 'approved', 'applied', 'rejected'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                    statusFilter === f ? 'bg-blue-600 text-white shadow-sm' : 'text-white/40 hover:text-white/70'
                  }`}
                >
                  {f === 'all' ? 'All Requests' : f.replace(/_/g, ' ').toUpperCase()}
                </button>
              ))}
            </div>
            <button onClick={() => { refetchReqs(); refetchStats() }} className="ml-auto flex items-center gap-1.5 text-[11px] text-white/40 hover:text-white/70">
              <RefreshCw className="w-3 h-3" /> Refresh Queue
            </button>
          </div>

          {actionError && (
            <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          {/* Requests Queue */}
          {reqsLoading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-5 h-5 text-white/30 animate-spin" />
            </div>
          ) : requests.length === 0 ? (
            <Card>
              <EmptyState
                icon={<ShieldCheck className="w-5 h-5" />}
                title="No Knowledge Update Recommendations"
                description="When Domain Experts resolve tickets and identify outdated documents or missing knowledge, recommendations will appear here for Admin review."
              />
            </Card>
          ) : (
            <div className="space-y-3">
              {requests.map(req => {
                const rootCauseInfo = (req.root_cause as ResolutionType) && RESOLUTION_TYPE_LABELS[req.root_cause as ResolutionType]
                  ? RESOLUTION_TYPE_LABELS[req.root_cause as ResolutionType]
                  : null

                return (
                  <Card key={req.request_id} className="space-y-3">
                    <div className="flex items-start justify-between flex-wrap gap-2">
                      <div>
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="text-xs font-mono font-bold text-white/90">{req.request_id}</span>
                          <span className="text-xs text-white/30">from ticket</span>
                          <span className="text-xs font-mono text-blue-400">{req.ticket_id}</span>
                          {rootCauseInfo && (
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${rootCauseInfo.color}`}>
                              {rootCauseInfo.label}
                            </span>
                          )}
                          {getStatusBadge(req.status)}
                        </div>
                        <h4 className="text-sm font-semibold text-white/95">{req.title}</h4>
                      </div>

                      {/* Admin Governance Actions */}
                      <Can permission={[Permission.DOCUMENT_VERSION_MANAGE, Permission.DOMAIN_MANAGE]} any>
                        <div className="flex items-center gap-2">
                          {req.status === 'pending_review' && (
                            <>
                              <button
                                onClick={() => handleOpenReview(req, 'approve')}
                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-500/30 text-xs font-medium text-blue-300 hover:bg-blue-500/25 transition-all"
                              >
                                <Check className="w-3.5 h-3.5" /> Approve
                              </button>
                              <button
                                onClick={() => handleOpenReview(req, 'reject')}
                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs font-medium text-red-300 hover:bg-red-500/20 transition-all"
                              >
                                <XCircle className="w-3.5 h-3.5" /> Reject
                              </button>
                            </>
                          )}

                          {(req.status === 'approved' || req.status === 'pending_review') && (
                            <button
                              onClick={() => handleOpenApply(req)}
                              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30 transition-all shadow-sm"
                            >
                              <Sparkles className="w-3.5 h-3.5 text-emerald-400" /> Apply & Evolve Knowledge
                            </button>
                          )}
                        </div>
                      </Can>
                    </div>

                    {/* Content Details */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs bg-white/[0.015] border border-white/[0.05] rounded-xl p-3">
                      <div>
                        <p className="text-[10px] text-white/30 uppercase font-medium mb-1">Proposed Verified Knowledge</p>
                        <p className="text-emerald-300/90 leading-relaxed whitespace-pre-wrap">{req.suggested_resolution}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-white/30 uppercase font-medium mb-1">Target Document Lineage</p>
                        <p className="font-mono text-white/70">{req.target_filename || 'New Document Policy'}</p>
                        {req.supporting_document_ids && req.supporting_document_ids.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {req.supporting_document_ids.map(docId => (
                              <span key={docId} className="text-[10px] font-mono bg-white/[0.04] text-white/50 px-1.5 py-0.5 rounded">
                                {docId}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Resulting Document Linkage */}
                    {req.status === 'applied' && (
                      <div className="flex items-center gap-3 text-xs text-emerald-400 bg-emerald-500/[0.06] border border-emerald-500/15 rounded-xl px-3 py-2">
                        <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                        <span>Applied in Document: <strong className="font-mono">{req.applied_document_id}</strong> (Event: <strong className="font-mono">{req.change_event_id}</strong>)</span>
                      </div>
                    )}
                  </Card>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Review Modal */}
      {reviewModalReq && (
        <Modal
          open={!!reviewModalReq}
          onClose={() => setReviewModalReq(null)}
          title={`${reviewAction === 'approve' ? 'Approve' : 'Reject'} Knowledge Update Request`}
          maxWidth="max-w-md"
        >
          <div className="space-y-4 text-left">
            <p className="text-xs text-white/60">
              {reviewAction === 'approve'
                ? `Approve recommendation ${reviewModalReq.request_id}. Once approved, an administrator can execute the Evolution re-ingestion and incremental reindexing.`
                : `Reject recommendation ${reviewModalReq.request_id}. Please provide feedback rationale.`}
            </p>

            <div>
              <label className="text-xs font-medium text-white/70 mb-1 block">Reviewer Notes</label>
              <textarea
                value={adminNotes}
                onChange={e => setAdminNotes(e.target.value)}
                rows={3}
                placeholder="Rationale or instructions for ingestion..."
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 resize-none"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Btn variant="ghost" size="sm" onClick={() => setReviewModalReq(null)} disabled={reviewing}>Cancel</Btn>
              <Btn size="sm" onClick={handleExecuteReview} disabled={reviewing}>
                {reviewing ? 'Saving…' : `Confirm ${reviewAction === 'approve' ? 'Approval' : 'Rejection'}`}
              </Btn>
            </div>
          </div>
        </Modal>
      )}

      {/* Apply Update Modal */}
      {applyModalReq && (
        <Modal
          open={!!applyModalReq}
          onClose={() => setApplyModalReq(null)}
          title="Apply Knowledge Update (Evolution Engine)"
          maxWidth="max-w-xl"
        >
          <div className="space-y-4 text-left">
            <p className="text-xs text-white/60">
              Applying this update will trigger the full Knowledge Evolution pipeline:
              <strong className="text-white/80"> Version Comparison (Diff) $\to$ Concept Drift $\to$ Conflict Check $\to$ Incremental FAISS Reindexing</strong>.
              Document version history will be updated cleanly.
            </p>

            {applySuccessMsg && (
              <div className="px-3 py-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 flex items-center gap-2">
                <Check className="w-4 h-4 flex-shrink-0" />
                <span>{applySuccessMsg}</span>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-white/70 mb-1 block">Target Document Filename (Version Lineage Matching)</label>
                <input
                  type="text"
                  value={applyFilename}
                  onChange={e => setApplyFilename(e.target.value)}
                  placeholder="e.g. hr_remote_policy.txt"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 font-mono"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-white/70 mb-1 block">Authoritative Replacement / Updated Content</label>
                <textarea
                  value={applyText}
                  onChange={e => setApplyText(e.target.value)}
                  rows={6}
                  placeholder="Paste or edit the complete authoritative document text..."
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 resize-none font-sans leading-relaxed"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              <Btn variant="ghost" size="sm" onClick={() => setApplyModalReq(null)} disabled={applying}>Cancel</Btn>
              <Btn size="sm" onClick={handleExecuteApply} disabled={applying || !applyText.trim()}>
                {applying ? 'Running Evolution Pipeline…' : 'Execute & Evolve Knowledge'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
