'use client'
import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Ticket as TicketIcon, ChevronDown, ChevronUp, Loader2, AlertTriangle,
  UserCheck, CheckCircle2, XCircle, RotateCcw, FileText, Check,
  Sparkles, Layers, BookOpen, Clock, ShieldCheck, Tag, Info, GitBranch, ArrowUpRight, PlusCircle,
} from 'lucide-react'
import { Can, PageHeader, ConfidenceMeter, EmptyState, Modal, Btn } from '@/components/shared/index'
import { ticketsApi, knowledgeUpdatesApi, ApiError } from '@/lib/api'
import type {
  TicketOut, TicketStatsResponse, TicketStatus,
  ResolutionType, KnowledgeUpdateRequest,
} from '@/lib/api'
import { RESOLUTION_TYPE_LABELS } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission } from '@/lib/rbac'

const statusStyles: Record<string, string> = {
  open: 'bg-red-500/15 text-red-400 border-red-500/25',
  needs_triage: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  routed: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  assigned: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25',
  in_progress: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  in_review: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  resolved: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  closed: 'bg-gray-500/15 text-gray-400 border-gray-500/25',
  dismissed: 'bg-gray-500/15 text-gray-400 border-gray-500/25',
  rejected: 'bg-rose-500/15 text-rose-400 border-rose-500/25',
}

const statusLabels: Record<string, string> = {
  open: 'Open',
  needs_triage: 'Needs Triage',
  routed: 'Routed',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  in_review: 'In Review',
  resolved: 'Resolved',
  closed: 'Closed',
  dismissed: 'Dismissed',
  rejected: 'Rejected',
}

export default function TicketsPage() {
  const [tickets, setTickets] = useState<TicketOut[]>([])
  const [stats, setStats] = useState<TicketStatsResponse | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('open')
  const [departmentFilter, setDepartmentFilter] = useState<string>('all')
  const [resolutionTypeFilter, setResolutionTypeFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Resolution workflow state for expanded ticket
  const [resolutionType, setResolutionType] = useState<ResolutionType>('KNOWLEDGE_MISSING')
  const [correctedAnswer, setCorrectedAnswer] = useState('')
  const [supportingEvidence, setSupportingEvidence] = useState('')
  const [supportingDocsInput, setSupportingDocsInput] = useState('')
  const [internalNotes, setInternalNotes] = useState('')

  // Knowledge Update Request Modal State (Phase 14)
  const [knowledgeModalTicket, setKnowledgeModalTicket] = useState<TicketOut | null>(null)
  const [updateTitle, setUpdateTitle] = useState('')
  const [updateDescription, setUpdateDescription] = useState('')
  const [updateTargetFilename, setUpdateTargetFilename] = useState('')
  const [creatingUpdate, setCreatingUpdate] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, s] = await Promise.all([
        ticketsApi.list({
          status: statusFilter === 'all' ? undefined : statusFilter,
          domain: departmentFilter === 'all' ? undefined : departmentFilter,
          resolution_type: resolutionTypeFilter === 'all' ? undefined : resolutionTypeFilter,
          limit: 100,
        }),
        ticketsApi.stats(),
      ])
      setTickets(list.tickets)
      setStats(s)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load tickets. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [statusFilter, departmentFilter, resolutionTypeFilter])

  useEffect(() => { load() }, [load])

  const toggleExpand = (t: TicketOut) => {
    const next = expanded === t.ticket_id ? null : t.ticket_id
    setExpanded(next)
    if (next) {
      setCorrectedAnswer(t.resolution || t.corrected_answer || '')
      setResolutionType(
        (t.resolution_type as ResolutionType) && RESOLUTION_TYPE_LABELS[t.resolution_type as ResolutionType]
          ? (t.resolution_type as ResolutionType)
          : 'KNOWLEDGE_MISSING'
      )
      setSupportingEvidence(t.supporting_evidence || '')
      setSupportingDocsInput(
        t.supporting_document_ids && t.supporting_document_ids.length > 0
          ? t.supporting_document_ids.join(', ')
          : ''
      )
      setInternalNotes(t.feedback || t.reviewer_notes || '')
    } else {
      setCorrectedAnswer('')
      setSupportingEvidence('')
      setSupportingDocsInput('')
      setInternalNotes('')
    }
  }

  const handleResolve = async (ticketId: string) => {
    if (!correctedAnswer.trim()) {
      setError('Please provide a corrected resolution answer before resolving.')
      return
    }
    setSaving(true)
    setError(null)
    setSuccessMsg(null)

    const docIds = supportingDocsInput
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)

    try {
      await ticketsApi.resolve(ticketId, {
        resolution: correctedAnswer.trim(),
        resolution_type: resolutionType,
        supporting_evidence: supportingEvidence.trim() || undefined,
        supporting_document_ids: docIds.length > 0 ? docIds : undefined,
        internal_notes: internalNotes.trim() || undefined,
      })
      setSuccessMsg(`Ticket ${ticketId} resolved successfully. Feedback saved for Continuous Learning.`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to resolve ticket.')
    } finally {
      setSaving(false)
    }
  }

  const handleStatusChange = async (ticketId: string, nextStatus: TicketStatus) => {
    setSaving(true)
    setError(null)
    setSuccessMsg(null)
    try {
      if (nextStatus === 'closed' || nextStatus === 'dismissed') {
        await ticketsApi.close(ticketId, { feedback: internalNotes.trim() || undefined })
      } else {
        await ticketsApi.update(ticketId, { status: nextStatus, reviewer_notes: internalNotes.trim() || undefined })
      }
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update ticket status.')
    } finally {
      setSaving(false)
    }
  }

  const openKnowledgeUpdateModal = (t: TicketOut) => {
    setKnowledgeModalTicket(t)
    setUpdateTitle(`Update Knowledge: ${t.title || t.original_question || t.ticket_id}`.slice(0, 100))
    setUpdateDescription(
      `Issue identified in ticket ${t.ticket_id}.\nOriginal Question: ${t.original_question || t.query_text}\nRoot Cause: ${t.resolution_type || 'KNOWLEDGE_MISSING'}\n\nExpert Verified Answer:\n${t.resolution || t.corrected_answer || t.generated_answer || ''}`
    )
    const firstDoc = t.source_document_ids && t.source_document_ids.length > 0 ? `${t.source_document_ids[0]}.txt` : `${t.domain || 'knowledge'}_policy.txt`
    setUpdateTargetFilename(firstDoc)
  }

  const handleCreateKnowledgeUpdateRequest = async () => {
    if (!knowledgeModalTicket) return
    setCreatingUpdate(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await ticketsApi.createKnowledgeUpdate(knowledgeModalTicket.ticket_id, {
        ticket_id: knowledgeModalTicket.ticket_id,
        title: updateTitle.trim() || `Knowledge Update for ${knowledgeModalTicket.ticket_id}`,
        description: updateDescription.trim(),
        suggested_resolution: knowledgeModalTicket.resolution || knowledgeModalTicket.corrected_answer || knowledgeModalTicket.generated_answer || 'Pending update',
        target_filename: updateTargetFilename.trim() || undefined,
        domain: knowledgeModalTicket.domain || undefined,
        root_cause: knowledgeModalTicket.resolution_type || 'KNOWLEDGE_MISSING',
        supporting_evidence: knowledgeModalTicket.supporting_evidence || knowledgeModalTicket.evidence || undefined,
        supporting_document_ids: knowledgeModalTicket.supporting_document_ids || knowledgeModalTicket.source_document_ids || [],
      })
      setSuccessMsg(`Knowledge Update Request ${res.request_id} created! Staged for Admin Evolution Review.`)
      setKnowledgeModalTicket(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create Knowledge Update Request.')
    } finally {
      setCreatingUpdate(false)
    }
  }

  const departments = stats ? Object.keys(stats.by_domain || stats.by_department || {}).sort() : []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Domain Expert Ticket Resolution"
        description="Phase 13 & 14: Review low-confidence queries, inspect evidence, provide authoritative answers, and trigger Knowledge Evolution recommendations."
      />

      {/* Analytics Summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: 'Open Queue', value: stats.open, color: 'text-red-400' },
            { label: 'In Review / Assigned', value: (stats.in_review || 0) + (stats.assigned || 0) + (stats.in_progress || 0), color: 'text-amber-400' },
            { label: 'Resolved Tickets', value: stats.resolved, color: 'text-emerald-400' },
            { label: 'Overdue (SLA)', value: stats.overdue_tickets ?? 0, color: 'text-rose-400' },
            {
              label: 'Avg Confidence (Open)',
              value: stats.avg_confidence_open !== null && stats.avg_confidence_open !== undefined
                ? `${Math.round(stats.avg_confidence_open * 100)}%`
                : '—',
              color: 'text-violet-400',
            },
          ].map((s, i) => (
            <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
              className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-4">
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-[11px] text-white/40 mt-1">{s.label}</p>
            </motion.div>
          ))}
        </div>
      )}

      {/* Filters & Actions */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1">
          {(['open', 'in_review', 'resolved', 'closed', 'all'] as const).map(f => (
            <button key={f} onClick={() => setStatusFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all ${statusFilter === f ? 'bg-blue-600 text-white shadow-sm' : 'text-white/40 hover:text-white/70'}`}>
              {f === 'all' ? 'All' : statusLabels[f] || f}
            </button>
          ))}
        </div>

        {departments.length > 0 && (
          <select
            value={departmentFilter}
            onChange={e => setDepartmentFilter(e.target.value)}
            className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white/70 outline-none focus:border-blue-500/50"
          >
            <option value="all">All Domains</option>
            {departments.map(d => <option key={d} value={d}>{d.toUpperCase()}</option>)}
          </select>
        )}

        <select
          value={resolutionTypeFilter}
          onChange={e => setResolutionTypeFilter(e.target.value)}
          className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white/70 outline-none focus:border-blue-500/50"
        >
          <option value="all">All Resolution Types</option>
          {Object.entries(RESOLUTION_TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>

        <button onClick={load} className="ml-auto flex items-center gap-1.5 text-[11px] text-white/40 hover:text-white/70 transition-colors">
          <RotateCcw className="w-3 h-3" /> Refresh
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 flex items-center gap-2">
          <Check className="w-4 h-4 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Ticket Queue List */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-5 h-5 text-white/30 animate-spin" />
        </div>
      ) : tickets.length === 0 ? (
        <EmptyState
          icon={<TicketIcon className="w-5 h-5" />}
          title="No tickets found"
          description="Low confidence answers and routed escalations will appear in this domain queue."
        />
      ) : (
        <div className="space-y-3">
          {tickets.map((t, i) => {
            const isResolved = t.status === 'resolved' || t.status === 'closed'
            const currentResType = (t.resolution_type as ResolutionType) && RESOLUTION_TYPE_LABELS[t.resolution_type as ResolutionType]
              ? (t.resolution_type as ResolutionType)
              : null

            return (
              <motion.div key={t.ticket_id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}
                className="bg-white/[0.03] border border-white/[0.07] rounded-2xl overflow-hidden shadow-sm">
                <button className="w-full flex items-center gap-4 p-4 text-left hover:bg-white/[0.02] transition-colors"
                  onClick={() => toggleExpand(t)}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                      <p className="text-sm font-medium text-white/90 truncate">{t.original_question || t.query_text}</p>
                      {t.occurrence_count > 1 && (
                        <span className="text-[10px] bg-red-500/15 text-red-400 px-1.5 py-0.5 rounded-full flex-shrink-0">
                          ×{t.occurrence_count}
                        </span>
                      )}
                      {currentResType && (
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${RESOLUTION_TYPE_LABELS[currentResType].color}`}>
                          {RESOLUTION_TYPE_LABELS[currentResType].label}
                        </span>
                      )}
                      {t.is_overdue && (
                        <span className="text-[10px] bg-rose-500/15 text-rose-400 border border-rose-500/25 px-1.5 py-0.5 rounded-full font-medium">
                          SLA Overdue
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-white/40 flex-wrap">
                      <span className="font-mono">{t.ticket_id}</span>
                      <span>·</span>
                      <span>{formatDateTime(t.created_at)}</span>
                      <span>·</span>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/15 text-blue-400">
                        {t.domain || t.department || 'General'}
                      </span>
                      {t.priority && (
                        <span className="text-[10px] uppercase font-mono text-white/50">
                          Priority: {t.priority}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0">
                    <span className={`px-2.5 py-1 rounded-full text-[10px] font-medium border ${statusStyles[t.status] || 'bg-gray-500/15 text-gray-400 border-gray-500/25'}`}>
                      {statusLabels[t.status] || t.status}
                    </span>
                    <div className="w-20 hidden sm:block">
                      <ConfidenceMeter value={t.confidence_score} size="sm" />
                    </div>
                    {expanded === t.ticket_id ? <ChevronUp className="w-4 h-4 text-white/30" /> : <ChevronDown className="w-4 h-4 text-white/30" />}
                  </div>
                </button>

                {/* Expanded Domain Expert Resolution Workspace */}
                {expanded === t.ticket_id && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                    className="border-t border-white/[0.06] p-5 bg-white/[0.015] space-y-5">
                    
                    {/* Query & Flagged Answer Inspection */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <p className="text-[10px] text-white/40 mb-1.5 uppercase font-medium tracking-wider flex items-center gap-1.5">
                          <BookOpen className="w-3 h-3 text-blue-400" /> Original Question
                        </p>
                        <div className="text-xs text-white/80 leading-relaxed bg-white/[0.02] border border-white/[0.06] rounded-xl p-3">
                          {t.original_question || t.query_text}
                        </div>
                      </div>
                      <div>
                        <p className="text-[10px] text-white/40 mb-1.5 uppercase font-medium tracking-wider flex items-center gap-1.5">
                          <AlertTriangle className="w-3 h-3 text-amber-400" /> Generated Answer (Flagged Low Confidence)
                        </p>
                        <div className="text-xs text-white/60 leading-relaxed bg-amber-500/[0.04] border border-amber-500/15 rounded-xl p-3 whitespace-pre-wrap">
                          {t.generated_answer || t.answer_text || '—'}
                        </div>
                      </div>
                    </div>

                    {/* Retrieved Evidence & Source Documents */}
                    <div>
                      <p className="text-[10px] text-white/40 mb-2 uppercase font-medium tracking-wider flex items-center gap-1.5">
                        <Layers className="w-3 h-3 text-violet-400" /> Retrieved Evidence & Citations
                      </p>
                      {t.evidence && (
                        <p className="text-xs text-white/60 mb-2 italic bg-white/[0.02] border border-white/[0.05] rounded-xl p-2.5">
                          &ldquo;{t.evidence}&rdquo;
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {t.source_document_ids && t.source_document_ids.length > 0 ? (
                          t.source_document_ids.map(docId => (
                            <span key={docId} className="inline-flex items-center gap-1.5 text-[11px] bg-violet-500/10 text-violet-300 border border-violet-500/20 px-2.5 py-1 rounded-lg font-mono">
                              <FileText className="w-3 h-3" /> {docId}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-white/30 italic">No retrieved source documents linked.</span>
                        )}
                      </div>
                    </div>

                    {/* Resolution Section */}
                    {isResolved ? (
                      <div className="space-y-4 pt-2 border-t border-white/[0.06]">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <div className="flex items-center gap-2">
                            <ShieldCheck className="w-4 h-4 text-emerald-400" />
                            <span className="text-xs font-semibold text-emerald-400">Verified Ticket Resolution</span>
                            {currentResType && (
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${RESOLUTION_TYPE_LABELS[currentResType].color}`}>
                                {RESOLUTION_TYPE_LABELS[currentResType].label}
                              </span>
                            )}
                          </div>

                          {/* Phase 14: Connect Ticket to Knowledge Evolution Engine */}
                          <Can permission={[Permission.TICKET_RESOLVE, Permission.DOCUMENT_VERSION_MANAGE, Permission.DOMAIN_MANAGE]} any>
                            <button
                              onClick={() => openKnowledgeUpdateModal(t)}
                              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-violet-500/15 border border-violet-500/30 text-xs font-semibold text-violet-300 hover:bg-violet-500/25 transition-all shadow-sm"
                            >
                              <GitBranch className="w-3.5 h-3.5 text-violet-400" /> Create Knowledge Update Request
                            </button>
                          </Can>
                        </div>

                        {t.resolution && (
                          <div>
                            <p className="text-[10px] text-white/40 mb-1 uppercase font-medium tracking-wider">Corrected Authoritative Answer</p>
                            <div className="text-xs text-emerald-300/90 leading-relaxed bg-emerald-500/[0.07] border border-emerald-500/20 rounded-xl p-3.5 whitespace-pre-wrap font-medium">
                              {t.resolution}
                            </div>
                          </div>
                        )}

                        {t.supporting_evidence && (
                          <div>
                            <p className="text-[10px] text-white/40 mb-1 uppercase font-medium tracking-wider">Supporting Evidence / Reference</p>
                            <p className="text-xs text-white/60 bg-white/[0.02] border border-white/[0.06] rounded-xl p-3">{t.supporting_evidence}</p>
                          </div>
                        )}

                        {t.supporting_document_ids && t.supporting_document_ids.length > 0 && (
                          <div>
                            <p className="text-[10px] text-white/40 mb-1 uppercase font-medium tracking-wider">Authoritative Attached Documents</p>
                            <div className="flex flex-wrap gap-1.5">
                              {t.supporting_document_ids.map(d => (
                                <span key={d} className="inline-flex items-center gap-1 text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 px-2 py-0.5 rounded-md font-mono">
                                  <FileText className="w-3 h-3" /> {d}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-[11px] text-white/40 pt-1">
                          <div>
                            <span className="text-white/30">Resolved By:</span>{' '}
                            <span className="text-white/70 font-medium">{t.resolver_user?.email || t.resolved_by || 'Domain Expert'}</span>
                          </div>
                          <div>
                            <span className="text-white/30">Resolved At:</span>{' '}
                            <span className="text-white/70">{t.resolved_at ? formatDateTime(t.resolved_at) : '—'}</span>
                          </div>
                        </div>

                        <Can permission={[Permission.TICKET_RESOLVE, Permission.TICKET_CLOSE]} any>
                          <button disabled={saving} onClick={() => handleStatusChange(t.ticket_id, 'open')}
                            className="flex items-center gap-1.5 text-[11px] text-white/40 hover:text-white/70 transition-colors disabled:opacity-50 mt-2">
                            <RotateCcw className="w-3 h-3" /> Reopen Ticket for Review
                          </button>
                        </Can>
                      </div>
                    ) : (
                      <Can
                        permission={[Permission.TICKET_RESOLVE, Permission.TICKET_ASSIGN, Permission.TICKET_CLOSE]}
                        any
                        fallback={<p className="text-xs text-white/30 italic">Awaiting review by an authorized Domain Expert or Manager.</p>}
                      >
                        <div className="space-y-4 pt-2 border-t border-white/[0.06]">
                          {/* Resolution Type Selection */}
                          <div>
                            <label className="text-[11px] font-semibold text-white/80 mb-1.5 block flex items-center gap-1.5">
                              <Tag className="w-3.5 h-3.5 text-blue-400" /> Root Cause / Resolution Type <span className="text-rose-400">*</span>
                            </label>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                              {(Object.keys(RESOLUTION_TYPE_LABELS) as ResolutionType[]).map(rType => {
                                const info = RESOLUTION_TYPE_LABELS[rType]
                                const isSelected = resolutionType === rType
                                return (
                                  <button
                                    key={rType}
                                    type="button"
                                    onClick={() => setResolutionType(rType)}
                                    className={`p-2.5 rounded-xl border text-left transition-all ${
                                      isSelected
                                        ? 'bg-blue-600/20 border-blue-500/50 text-white shadow-sm ring-1 ring-blue-500/30'
                                        : 'bg-white/[0.02] border-white/[0.06] text-white/60 hover:bg-white/[0.04] hover:text-white/80'
                                    }`}
                                  >
                                    <p className="text-[11px] font-semibold flex items-center justify-between">
                                      <span>{info.label}</span>
                                      {isSelected && <Check className="w-3 h-3 text-blue-400" />}
                                    </p>
                                    <p className="text-[10px] text-white/40 mt-1 leading-snug line-clamp-2">{info.description}</p>
                                  </button>
                                )
                              })}
                            </div>
                          </div>

                          {/* Corrected Answer Text */}
                          <div>
                            <label className="text-[11px] font-semibold text-white/80 mb-1.5 block flex items-center gap-1.5">
                              <Sparkles className="w-3.5 h-3.5 text-emerald-400" /> Corrected Authoritative Answer <span className="text-rose-400">*</span>
                            </label>
                            <textarea
                              value={correctedAnswer}
                              onChange={e => setCorrectedAnswer(e.target.value)}
                              rows={3}
                              placeholder="Enter the verified, domain-expert corrected answer..."
                              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2.5 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 resize-none font-sans"
                            />
                          </div>

                          {/* Supporting Evidence & Supporting Document Attachment */}
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                              <label className="text-[11px] font-medium text-white/70 mb-1 block flex items-center gap-1">
                                <Info className="w-3 h-3 text-violet-400" /> Supporting Evidence Explanation
                              </label>
                              <textarea
                                value={supportingEvidence}
                                onChange={e => setSupportingEvidence(e.target.value)}
                                rows={2}
                                placeholder="Explain why this answer is authoritative (section, guideline, policy)..."
                                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 resize-none"
                              />
                            </div>
                            <div>
                              <label className="text-[11px] font-medium text-white/70 mb-1 block flex items-center gap-1">
                                <FileText className="w-3 h-3 text-emerald-400" /> Attach Supporting Document IDs
                              </label>
                              <input
                                type="text"
                                value={supportingDocsInput}
                                onChange={e => setSupportingDocsInput(e.target.value)}
                                placeholder="e.g. DOC_HR_POLICY_2026, DOC_LEAVE_SEC_4"
                                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 font-mono"
                              />
                              <p className="text-[10px] text-white/30 mt-1">Comma-separated document IDs from authorized repositories.</p>
                            </div>
                          </div>

                          {/* Internal Notes */}
                          <div>
                            <label className="text-[11px] font-medium text-white/70 mb-1 block">Internal Reviewer Notes</label>
                            <input
                              type="text"
                              value={internalNotes}
                              onChange={e => setInternalNotes(e.target.value)}
                              placeholder="Internal triage or reviewer rationale (not exposed to client queries)..."
                              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50"
                            />
                          </div>

                          {/* Action Buttons */}
                          <div className="flex items-center justify-between flex-wrap gap-2 pt-2">
                            <div className="flex items-center gap-2 flex-wrap">
                              <Can permission={Permission.TICKET_RESOLVE}>
                                <button
                                  disabled={saving}
                                  onClick={() => handleResolve(t.ticket_id)}
                                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-500/20 border border-emerald-500/30 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30 transition-all disabled:opacity-50 shadow-sm"
                                >
                                  <CheckCircle2 className="w-4 h-4 text-emerald-400" /> Resolve Ticket
                                </button>
                              </Can>

                              {t.status === 'open' && (
                                <Can permission={Permission.TICKET_ASSIGN}>
                                  <button
                                    disabled={saving}
                                    onClick={() => handleStatusChange(t.ticket_id, 'in_review')}
                                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-amber-500/15 border border-amber-500/25 text-xs font-medium text-amber-300 hover:bg-amber-500/25 transition-all disabled:opacity-50"
                                  >
                                    <UserCheck className="w-3.5 h-3.5" /> Start Review
                                  </button>
                                </Can>
                              )}

                              <Can permission={Permission.TICKET_CLOSE}>
                                <button
                                  disabled={saving}
                                  onClick={() => handleStatusChange(t.ticket_id, 'closed')}
                                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-xs font-medium text-white/60 hover:text-white/90 transition-all disabled:opacity-50"
                                >
                                  <XCircle className="w-3.5 h-3.5" /> Close / Dismiss
                                </button>
                              </Can>

                              {saving && <Loader2 className="w-4 h-4 text-white/30 animate-spin ml-2" />}
                            </div>

                            {/* Phase 14: Shortcut to Stage Knowledge Update */}
                            <button
                              type="button"
                              onClick={() => openKnowledgeUpdateModal(t)}
                              className="flex items-center gap-1.5 text-xs text-violet-400 hover:text-violet-300 font-medium px-3 py-1.5 rounded-lg border border-violet-500/20 bg-violet-500/10 hover:bg-violet-500/20 transition-all"
                            >
                              <GitBranch className="w-3.5 h-3.5" /> Stage Knowledge Evolution Update
                            </button>
                          </div>
                        </div>
                      </Can>
                    )}
                  </motion.div>
                )}
              </motion.div>
            )
          })}
        </div>
      )}

      {/* Phase 14: Create Knowledge Update Request Modal */}
      {knowledgeModalTicket && (
        <Modal
          open={!!knowledgeModalTicket}
          onClose={() => setKnowledgeModalTicket(null)}
          title="Create Knowledge Update Request (Phase 14)"
          maxWidth="max-w-xl"
        >
          <div className="space-y-4 text-left">
            <p className="text-xs text-white/50">
              Stage a formal Knowledge Update proposal derived from ticket <span className="font-mono text-white/80">{knowledgeModalTicket.ticket_id}</span>.
              This recommendation will be sent to Administrators for review before any document changes or FAISS reindexing occur.
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-white/70 mb-1 block">Update Proposal Title</label>
                <input
                  type="text"
                  value={updateTitle}
                  onChange={e => setUpdateTitle(e.target.value)}
                  placeholder="e.g. Update Remote Work Equipment Reimbursement Policy"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-white/70 mb-1 block">Root Cause Classification</label>
                  <div className="px-3 py-2 rounded-xl bg-white/[0.03] border border-white/[0.08] text-xs font-semibold text-white/90 capitalize">
                    {knowledgeModalTicket.resolution_type ? RESOLUTION_TYPE_LABELS[knowledgeModalTicket.resolution_type as ResolutionType]?.label || knowledgeModalTicket.resolution_type : 'Knowledge Missing'}
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-white/70 mb-1 block">Target Document / Lineage Filename</label>
                  <input
                    type="text"
                    value={updateTargetFilename}
                    onChange={e => setUpdateTargetFilename(e.target.value)}
                    placeholder="e.g. hr_remote_policy.txt"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-white/70 mb-1 block">Proposed Knowledge / Rationale</label>
                <textarea
                  value={updateDescription}
                  onChange={e => setUpdateDescription(e.target.value)}
                  rows={4}
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 resize-none font-sans"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.06]">
              <Btn variant="ghost" size="sm" onClick={() => setKnowledgeModalTicket(null)} disabled={creatingUpdate}>
                Cancel
              </Btn>
              <Btn size="sm" onClick={handleCreateKnowledgeUpdateRequest} disabled={creatingUpdate || !updateTitle.trim()}>
                {creatingUpdate ? 'Staging Request…' : 'Submit Knowledge Update Request'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
