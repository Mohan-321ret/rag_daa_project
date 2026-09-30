'use client'
import { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Ticket as TicketIcon, ChevronRight, Loader2, AlertTriangle,
  UserCheck, CheckCircle2, RotateCcw, FileText, Check,
  Sparkles, Layers, BookOpen, ShieldCheck, Tag, Info, GitBranch,
  Play, RefreshCw, Search, User, Shield, X, HelpCircle, Upload, Paperclip
} from 'lucide-react'
import { Can, PageHeader, ConfidenceMeter, EmptyState, Modal, Btn } from '@/components/shared/index'
import { ticketsApi, ApiError } from '@/lib/api'
import type {
  TicketOut, TicketStatsResponse, TicketStatus,
  ResolutionType, KnowledgeUpdateRequest, TicketAttachment,
} from '@/lib/api'
import { RESOLUTION_TYPE_LABELS } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission, Role } from '@/lib/rbac'
import { useRole } from '@/lib/usePermission'

const statusStyles: Record<string, string> = {
  open: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/25',
  needs_triage: 'bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/25',
  routed: 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/25',
  assigned: 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 border-indigo-500/25',
  in_progress: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/25',
  in_review: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/25',
  resolved: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/25',
  closed: 'bg-gray-500/15 text-gray-600 dark:text-gray-400 border-gray-500/25',
  dismissed: 'bg-gray-500/15 text-gray-600 dark:text-gray-400 border-gray-500/25',
  rejected: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/25',
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

const priorityStyles: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/25',
  high: 'bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/25',
  medium: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/25',
  low: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/25',
}

export default function DomainManagerTicketDashboard() {
  const role = useRole()
  const isDomainManagerOrAdmin = role === Role.DOMAIN_MANAGER || role === Role.SUPER_ADMIN || role === Role.PLATFORM_OWNER || role === Role.HR

  const [tickets, setTickets] = useState<TicketOut[]>([])
  const [stats, setStats] = useState<TicketStatsResponse | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [domainFilter, setDepartmentFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Selected Ticket for Modal Details View
  const [selectedTicket, setSelectedTicket] = useState<TicketOut | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Resolution Modal State
  const [resolveTicketModal, setResolveTicketModal] = useState<TicketOut | null>(null)
  const [resolutionType, setResolutionType] = useState<ResolutionType>('TEXT')
  const [attachments, setAttachments] = useState<TicketAttachment[]>([])
  const [selectedAttachmentId, setSelectedAttachmentId] = useState<string | null>(null)
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [correctedAnswer, setCorrectedAnswer] = useState('')
  const [supportingEvidence, setSupportingEvidence] = useState('')
  const [supportingDocsInput, setSupportingDocsInput] = useState('')
  const [internalNotes, setInternalNotes] = useState('')
  const [resolving, setResolving] = useState(false)

  // Knowledge Update Request Modal State (Phase 14)
  const [knowledgeModalTicket, setKnowledgeModalTicket] = useState<TicketOut | null>(null)
  const [updateTitle, setUpdateTitle] = useState('')
  const [updateDescription, setUpdateDescription] = useState('')
  const [updateTargetFilename, setUpdateTargetFilename] = useState('')
  const [creatingUpdate, setCreatingUpdate] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // If user is domain manager, attempt manager listing first, fallback to standard listing
      let listRes: { tickets: TicketOut[]; total: number }
      if (role === Role.DOMAIN_MANAGER) {
        try {
          listRes = await ticketsApi.listManager({ limit: 100 })
        } catch {
          listRes = await ticketsApi.list({ limit: 100 })
        }
      } else {
        listRes = await ticketsApi.list({ limit: 100 })
      }
      const s = await ticketsApi.stats().catch(() => null)

      setTickets(listRes.tickets)
      setStats(s)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load tickets. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [role])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Open ticket detail modal and fetch enriched data
  const handleOpenDetail = async (ticket: TicketOut) => {
    setSelectedTicket(ticket)
    setDetailLoading(true)
    try {
      const enriched = await ticketsApi.get(ticket.ticket_id)
      setSelectedTicket(enriched)
    } catch (err) {
      console.warn('Failed to fetch detailed ticket context', err)
    } finally {
      setDetailLoading(false)
    }
  }

  // Action: [Start Working] -> status: in_progress
  const handleStartWorking = async (ticketId: string) => {
    setActionLoading(ticketId)
    setError(null)
    setSuccessMsg(null)
    try {
      const updated = await ticketsApi.updateStatus(ticketId, 'in_progress', 'Manager started working on this ticket')
      setSuccessMsg(`Ticket ${ticketId} status updated to In Progress.`)
      setTickets(prev => prev.map(t => t.ticket_id === ticketId ? { ...t, status: 'in_progress' } : t))
      if (selectedTicket?.ticket_id === ticketId) {
        setSelectedTicket(updated)
      }
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to set ticket to In Progress.')
    } finally {
      setActionLoading(null)
    }
  }

  // Action: Open [Resolve] Modal
  const openResolveModal = async (ticket: TicketOut) => {
    setResolveTicketModal(ticket)
    setCorrectedAnswer(ticket.resolution || ticket.corrected_answer || '')
    const initialResType = (ticket.resolution_type as ResolutionType) && RESOLUTION_TYPE_LABELS[ticket.resolution_type as ResolutionType]
      ? (ticket.resolution_type as ResolutionType)
      : 'TEXT'
    setResolutionType(initialResType)
    setSupportingEvidence(ticket.supporting_evidence || '')
    setSupportingDocsInput(
      ticket.supporting_document_ids && ticket.supporting_document_ids.length > 0
        ? ticket.supporting_document_ids.join(', ')
        : ''
    )
    setInternalNotes(ticket.feedback || ticket.reviewer_notes || '')
    setAttachmentError(null)

    // Load attachments for this ticket
    try {
      const atts = await ticketsApi.listAttachments(ticket.ticket_id)
      setAttachments(atts || [])
      if (atts && atts.length > 0) {
        setSelectedAttachmentId(atts[0].attachment_id)
        if (initialResType === 'TEXT') {
          setResolutionType('FILE')
        }
      } else {
        setSelectedAttachmentId(null)
      }
    } catch {
      setAttachments([])
      setSelectedAttachmentId(null)
    }
  }

  // Upload KB File in Resolution Modal
  const handleUploadKBFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!resolveTicketModal || !e.target.files?.[0]) return
    const file = e.target.files[0]
    setUploadingAttachment(true)
    setAttachmentError(null)
    try {
      const newAtt = await ticketsApi.uploadKb(resolveTicketModal.ticket_id, file, true)
      setAttachments(prev => [newAtt, ...prev.filter(a => a.attachment_id !== newAtt.attachment_id)])
      setSelectedAttachmentId(newAtt.attachment_id)
      if (resolutionType === 'TEXT') {
        setResolutionType('FILE')
      }
      setSuccessMsg(`Document ${file.name} uploaded successfully and ingested into Knowledge Base.`)
    } catch (err) {
      setAttachmentError(err instanceof ApiError ? err.message : 'Failed to upload document.')
    } finally {
      setUploadingAttachment(false)
      e.target.value = ''
    }
  }

  // Action: [Resolve] submit
  const handleResolveSubmit = async () => {
    if (!resolveTicketModal) return

    const targetAtt = attachments.find(a => a.attachment_id === selectedAttachmentId) || (attachments.length > 0 ? attachments[0] : null)

    // Strictly enforce resolution gating if FILE or BOTH is selected
    if (resolutionType === 'FILE' || resolutionType === 'BOTH') {
      if (!targetAtt && attachments.length === 0) {
        setError('File-based resolution requires an uploaded knowledge-base document.')
        return
      }
      if (targetAtt && (targetAtt.status === 'PENDING' || targetAtt.status === 'PROCESSING')) {
        setError(`Document '${targetAtt.original_filename}' processing is currently in progress (${targetAtt.status}). Ticket cannot be resolved until ingestion succeeds.`)
        return
      }
      if (targetAtt && targetAtt.status === 'FAILED') {
        setError(`Document processing failed for '${targetAtt.original_filename}': ${targetAtt.error_message || 'Ingestion failed'}. Please re-upload a valid document before resolving.`)
        return
      }
    }

    if ((resolutionType === 'TEXT' || resolutionType === 'BOTH') && !correctedAnswer.trim()) {
      setError('Please enter a textual resolution answer.')
      return
    }

    setResolving(true)
    setError(null)
    setSuccessMsg(null)

    const docIds = supportingDocsInput
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)

    try {
      const resolvedTicket = await ticketsApi.resolve(resolveTicketModal.ticket_id, {
        resolution: correctedAnswer.trim() || undefined,
        resolution_type: resolutionType,
        attachment_id: targetAtt?.attachment_id || selectedAttachmentId || undefined,
        supporting_evidence: supportingEvidence.trim() || undefined,
        supporting_document_ids: docIds.length > 0 ? docIds : undefined,
        internal_notes: internalNotes.trim() || undefined,
      })
      setSuccessMsg(`Ticket ${resolveTicketModal.ticket_id} successfully resolved!`)
      setResolveTicketModal(null)
      if (selectedTicket?.ticket_id === resolveTicketModal.ticket_id) {
        setSelectedTicket(resolvedTicket)
      }
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to resolve ticket.')
    } finally {
      setResolving(false)
    }
  }

  // Action: [Reopen] -> status: open
  const handleReopen = async (ticketId: string) => {
    setActionLoading(ticketId)
    setError(null)
    setSuccessMsg(null)
    try {
      const reopened = await ticketsApi.updateStatus(ticketId, 'open', 'Ticket reopened for further review')
      setSuccessMsg(`Ticket ${ticketId} has been reopened.`)
      setTickets(prev => prev.map(t => t.ticket_id === ticketId ? { ...t, status: 'open' } : t))
      if (selectedTicket?.ticket_id === ticketId) {
        setSelectedTicket(reopened)
      }
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to reopen ticket.')
    } finally {
      setActionLoading(null)
    }
  }

  // Knowledge Update Request Modal (Phase 14)
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
      await loadData()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create Knowledge Update Request.')
    } finally {
      setCreatingUpdate(false)
    }
  }

  // Metrics calculation
  const openCount = stats?.open ?? tickets.filter(t => t.status === 'open' || t.status === 'needs_triage' || t.status === 'routed').length
  const assignedCount = (stats?.assigned ?? 0) || tickets.filter(t => !!t.assigned_to || !!t.assigned_expert || t.status === 'assigned').length
  const inProgressCount = ((stats?.in_progress ?? 0) + (stats?.in_review ?? 0)) || tickets.filter(t => t.status === 'in_progress' || t.status === 'in_review').length
  const resolvedCount = stats?.resolved ?? tickets.filter(t => t.status === 'resolved' || t.status === 'closed').length

  // Filtering list
  const filteredTickets = tickets.filter(t => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (domainFilter !== 'all' && (t.domain || t.department || 'General').toLowerCase() !== domainFilter.toLowerCase()) return false
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      const matchId = t.ticket_id.toLowerCase().includes(q)
      const matchQuery = (t.original_question || t.query_text || t.title || '').toLowerCase().includes(q)
      const matchDomain = (t.domain || t.department || '').toLowerCase().includes(q)
      const matchAssigned = (t.assigned_expert?.full_name || t.assigned_expert?.email || t.assigned_to || '').toLowerCase().includes(q)
      if (!matchId && !matchQuery && !matchDomain && !matchAssigned) return false
    }
    return true
  })

  const domains = Array.from(new Set(tickets.map(t => t.domain || t.department || 'General'))).sort()

  return (
    <div className="space-y-6">
      <PageHeader
        title={isDomainManagerOrAdmin ? "Domain Manager Ticket Dashboard" : "My Support Tickets"}
        description={
          isDomainManagerOrAdmin
            ? "Manage low-confidence escalations, track domain workload, inspect RAG answers, and execute resolution workflows."
            : "View support tickets generated from your low-confidence AI queries and track their domain manager resolutions."
        }
      />

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Open Tickets', value: openCount, color: 'text-red-500 dark:text-red-400', border: 'border-red-500/20', bg: 'bg-red-500/5' },
          { label: 'Assigned Tickets', value: assignedCount, color: 'text-indigo-500 dark:text-indigo-400', border: 'border-indigo-500/20', bg: 'bg-indigo-500/5' },
          { label: 'In Progress', value: inProgressCount, color: 'text-amber-500 dark:text-amber-400', border: 'border-amber-500/20', bg: 'bg-amber-500/5' },
          { label: 'Resolved Tickets', value: resolvedCount, color: 'text-emerald-500 dark:text-emerald-400', border: 'border-emerald-500/20', bg: 'bg-emerald-500/5' },
        ].map((s, i) => (
          <motion.div
            key={s.label}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className={`bg-white dark:bg-white/[0.03] border ${s.border} rounded-2xl p-4 shadow-sm dark:shadow-none flex flex-col justify-between`}
          >
            <p className="text-xs font-medium text-gray-500 dark:text-white/50">{s.label}</p>
            <div className="flex items-baseline justify-between mt-2">
              <span className={`text-3xl font-extrabold ${s.color}`}>{s.value}</span>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${s.bg} ${s.color}`}>
                Active
              </span>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Notifications */}
      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-500 dark:text-red-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-2">
          <Check className="w-4 h-4 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Search & Filter Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-white/30" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by ticket ID, original query, domain, or resolution..."
            className="w-full bg-white dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 rounded-xl pl-9 pr-4 py-2 text-xs outline-none focus:border-blue-500 transition-all"
          />
        </div>

        <div className="flex items-center gap-1 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1">
          {(['all', 'open', 'in_progress', 'resolved'] as const).map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                statusFilter === f
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-600 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'
              }`}
            >
              {f === 'all' ? 'All Status' : statusLabels[f] || f}
            </button>
          ))}
        </div>

        {domains.length > 0 && (
          <select
            value={domainFilter}
            onChange={e => setDepartmentFilter(e.target.value)}
            className="bg-white dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-800 dark:text-white/80 rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500"
          >
            <option value="all" className="bg-white text-gray-900 dark:bg-[#12121f] dark:text-white">All Domains</option>
            {domains.map(d => (
              <option key={d} value={d} className="bg-white text-gray-900 dark:bg-[#12121f] dark:text-white">{d}</option>
            ))}
          </select>
        )}

        <button
          onClick={loadData}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-gray-600 dark:text-white/60 hover:text-gray-900 dark:hover:text-white bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.08] rounded-xl transition-all"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Ticket List Table */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
          <p className="text-xs text-gray-500 dark:text-white/40">Loading tickets...</p>
        </div>
      ) : filteredTickets.length === 0 ? (
        <EmptyState
          icon={<TicketIcon className="w-6 h-6" />}
          title="No tickets found"
          description="There are currently no tickets matching your active search or filter criteria."
        />
      ) : (
        <div className="bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl overflow-hidden shadow-sm dark:shadow-none">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-200 dark:border-white/[0.06] bg-gray-50/70 dark:bg-white/[0.02] text-gray-500 dark:text-white/40 font-semibold uppercase tracking-wider">
                  <th className="py-3 px-4">Ticket Number</th>
                  <th className="py-3 px-4">Original Query</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4">Domain</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Created Date</th>
                  <th className="py-3 px-4">Resolution</th>
                  <th className="py-3 px-4">Resolved Date</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-white/[0.04]">
                {filteredTickets.map(ticket => {
                  const isWorking = ticket.status === 'in_progress' || ticket.status === 'in_review'
                  const isResolved = ticket.status === 'resolved' || ticket.status === 'closed'
                  const resolutionText = ticket.resolution || ticket.corrected_answer

                  return (
                    <tr
                      key={ticket.ticket_id}
                      onClick={() => handleOpenDetail(ticket)}
                      className="hover:bg-gray-50/80 dark:hover:bg-white/[0.02] transition-colors cursor-pointer group"
                    >
                      {/* Ticket Number */}
                      <td className="py-3.5 px-4 font-mono font-semibold text-gray-900 dark:text-white/90 group-hover:text-blue-500 transition-colors">
                        {ticket.ticket_id}
                      </td>

                      {/* Original Query */}
                      <td className="py-3.5 px-4 max-w-xs">
                        <p className="text-gray-800 dark:text-white/80 font-medium truncate">
                          {ticket.original_question || ticket.query_text || ticket.user_question || ticket.title}
                        </p>
                      </td>

                      {/* Confidence Score */}
                      <td className="py-3.5 px-4 min-w-[100px]">
                        <ConfidenceMeter value={ticket.confidence_score} size="sm" />
                      </td>

                      {/* Domain */}
                      <td className="py-3.5 px-4">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 dark:bg-blue-500/15 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                          {ticket.domain || ticket.department || 'General'}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-4">
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-medium border ${statusStyles[ticket.status] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                          {statusLabels[ticket.status] || ticket.status}
                        </span>
                      </td>

                      {/* Created Date */}
                      <td className="py-3.5 px-4 text-gray-500 dark:text-white/40 whitespace-nowrap">
                        {formatDateTime(ticket.created_at)}
                      </td>

                      {/* Resolution */}
                      <td className="py-3.5 px-4 max-w-[180px]">
                        {resolutionText ? (
                          <span className="truncate block font-medium text-emerald-600 dark:text-emerald-400">
                            {resolutionText}
                          </span>
                        ) : (
                          <span className="text-gray-400 dark:text-white/30 italic">Pending</span>
                        )}
                      </td>

                      {/* Resolved Date */}
                      <td className="py-3.5 px-4 text-gray-500 dark:text-white/40 whitespace-nowrap">
                        {ticket.resolved_at ? formatDateTime(ticket.resolved_at) : '-'}
                      </td>

                      {/* Action buttons on row */}
                      <td className="py-3.5 px-4 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5">
                          {isDomainManagerOrAdmin ? (
                            <>
                              {!isWorking && !isResolved && (
                                <button
                                  disabled={actionLoading === ticket.ticket_id}
                                  onClick={() => handleStartWorking(ticket.ticket_id)}
                                  className="px-2.5 py-1 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 border border-amber-500/20 text-[11px] font-semibold transition-all flex items-center gap-1 disabled:opacity-50"
                                  title="Start working on ticket"
                                >
                                  <Play className="w-3 h-3 fill-current" />
                                  <span>Start Working</span>
                                </button>
                              )}

                              {!isResolved && (
                                <button
                                  onClick={() => openResolveModal(ticket)}
                                  className="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 text-[11px] font-semibold transition-all flex items-center gap-1"
                                  title="Resolve ticket"
                                >
                                  <CheckCircle2 className="w-3 h-3" />
                                  <span>Resolve</span>
                                </button>
                              )}

                              {isResolved && (
                                <button
                                  disabled={actionLoading === ticket.ticket_id}
                                  onClick={() => handleReopen(ticket.ticket_id)}
                                  className="px-2.5 py-1 rounded-lg bg-gray-500/10 text-gray-600 dark:text-gray-300 hover:bg-gray-500/20 border border-gray-500/20 text-[11px] font-semibold transition-all flex items-center gap-1 disabled:opacity-50"
                                  title="Reopen ticket"
                                >
                                  <RotateCcw className="w-3 h-3" />
                                  <span>Reopen</span>
                                </button>
                              )}
                            </>
                          ) : (
                            <button
                              onClick={() => handleOpenDetail(ticket)}
                              className="px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 hover:bg-blue-500/20 border border-blue-500/20 text-[11px] font-semibold transition-all flex items-center gap-1"
                            >
                              <span>View Details</span>
                            </button>
                          )}
                          <ChevronRight className="w-4 h-4 text-gray-400 group-hover:text-blue-500 transition-colors ml-1" />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Ticket Details Modal */}
      {selectedTicket && (
        <Modal
          open={!!selectedTicket}
          onClose={() => setSelectedTicket(null)}
          title={`Ticket Details — ${selectedTicket.ticket_id}`}
          maxWidth="max-w-3xl"
        >
          {detailLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
            </div>
          ) : (
            <div className="space-y-5 text-left text-xs">
              {/* Header Status & Metadata */}
              <div className="flex items-center justify-between flex-wrap gap-2 p-3.5 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl">
                <div className="flex items-center gap-2">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${statusStyles[selectedTicket.status] || 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                    {statusLabels[selectedTicket.status] || selectedTicket.status}
                  </span>
                  <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 dark:bg-blue-500/15 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20">
                    Domain: {selectedTicket.domain || selectedTicket.department || 'General'}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-gray-500 dark:text-white/40">
                  <span>Created: {formatDateTime(selectedTicket.created_at)}</span>
                </div>
              </div>

              {/* User Information (Privacy Compliant) */}
              <div className="p-3 bg-blue-50/50 dark:bg-blue-500/[0.03] border border-blue-200/60 dark:border-blue-500/15 rounded-xl flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-blue-500" />
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white/90">User Information</p>
                    <p className="text-[11px] text-gray-500 dark:text-white/50">
                      User ID: <span className="font-mono text-gray-800 dark:text-white/70">{selectedTicket.user_id || selectedTicket.raised_by_user_id || 'System Anonymous User'}</span>
                      {selectedTicket.assigned_expert && (
                        <span> · Assigned Expert: {selectedTicket.assigned_expert.full_name || selectedTicket.assigned_expert.email}</span>
                      )}
                    </p>
                  </div>
                </div>
              </div>

              {/* User Query */}
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-white/40 mb-1.5 flex items-center gap-1.5">
                  <BookOpen className="w-3.5 h-3.5 text-blue-500" /> User Query
                </p>
                <div className="p-3.5 bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl text-gray-900 dark:text-white/90 font-medium leading-relaxed">
                  {selectedTicket.original_question || selectedTicket.query_text || selectedTicket.user_question || selectedTicket.title}
                </div>
              </div>

              {/* Generated RAG Answer & Confidence Score */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="md:col-span-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-white/40 mb-1.5 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-500" /> Generated RAG Answer
                  </p>
                  <div className="p-3.5 bg-amber-50/50 dark:bg-amber-500/[0.03] border border-amber-200 dark:border-amber-500/15 rounded-xl text-gray-800 dark:text-white/80 whitespace-pre-wrap leading-relaxed">
                    {selectedTicket.generated_answer || selectedTicket.answer_text || 'No AI answer generated.'}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-white/40 mb-1.5 flex items-center gap-1.5">
                    <Tag className="w-3.5 h-3.5 text-violet-500" /> Confidence Score
                  </p>
                  <div className="p-3.5 bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl space-y-2">
                    <ConfidenceMeter value={selectedTicket.confidence_score} size="md" />
                    <p className="text-[10px] text-gray-400 dark:text-white/30">
                      Threshold: {Math.round((selectedTicket.confidence_threshold || 0.5) * 100)}%
                    </p>
                  </div>
                </div>
              </div>

              {/* Retrieved Sources / Chunks */}
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-white/40 mb-1.5 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-emerald-500" /> Retrieved Sources & Citations
                </p>
                {selectedTicket.evidence && (
                  <p className="p-2.5 mb-2 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.05] rounded-lg text-gray-600 dark:text-white/60 italic text-[11px]">
                    &ldquo;{selectedTicket.evidence}&rdquo;
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {selectedTicket.source_document_ids && selectedTicket.source_document_ids.length > 0 ? (
                    selectedTicket.source_document_ids.map(docId => (
                      <span key={docId} className="inline-flex items-center gap-1.5 text-[11px] bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 px-2.5 py-1 rounded-lg font-mono">
                        <FileText className="w-3.5 h-3.5" /> {docId}
                      </span>
                    ))
                  ) : (
                    <span className="text-gray-400 dark:text-white/30 italic">No retrieved source documents linked.</span>
                  )}
                </div>
              </div>

              {/* Verified Manager Resolution if available */}
              {(selectedTicket.resolution || selectedTicket.corrected_answer) && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5" /> Domain Expert Resolution Answer
                    </p>
                    {selectedTicket.resolved_at && (
                      <span className="text-[10px] text-gray-500 dark:text-white/40">
                        Resolved: {formatDateTime(selectedTicket.resolved_at)}
                      </span>
                    )}
                  </div>
                  <div className="p-3.5 bg-emerald-50 dark:bg-emerald-500/[0.07] border border-emerald-200 dark:border-emerald-500/20 rounded-xl text-emerald-900 dark:text-emerald-300 font-medium whitespace-pre-wrap leading-relaxed">
                    {selectedTicket.resolution || selectedTicket.corrected_answer}
                  </div>
                  {selectedTicket.resolution_type && (
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-gray-500 dark:text-white/40">Resolution Mode:</span>
                      <span className="px-2 py-0.5 rounded-md font-mono bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                        {selectedTicket.resolution_type} {selectedTicket.resolution_format ? `(${selectedTicket.resolution_format})` : ''}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Knowledge Base Document Information */}
              {selectedTicket.attachments && selectedTicket.attachments.length > 0 && (
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400 flex items-center gap-1.5">
                    <Paperclip className="w-3.5 h-3.5" /> Resolution Knowledge-Base Documents
                  </p>
                  <div className="space-y-1.5">
                    {selectedTicket.attachments.map(att => (
                      <div key={att.attachment_id} className="p-2.5 rounded-xl border border-blue-200/70 dark:border-blue-500/20 bg-blue-50/40 dark:bg-blue-500/5 flex items-center justify-between">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileText className="w-4 h-4 text-blue-500 shrink-0" />
                          <div className="min-w-0">
                            <p className="font-semibold text-gray-800 dark:text-white truncate text-xs">
                              {att.original_filename}
                            </p>
                            <p className="text-[10px] text-gray-400 dark:text-white/40 font-mono">
                              ID: {att.attachment_id} • {att.file_type} {att.file_size ? `• ${(att.file_size / 1024).toFixed(1)} KB` : ''}
                            </p>
                          </div>
                        </div>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Indexed in KB
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Details Modal Action Bar (Gated by RBAC) */}
              <div className="flex items-center justify-between flex-wrap gap-2 pt-4 border-t border-gray-200 dark:border-white/[0.06]">
                {isDomainManagerOrAdmin ? (
                  <div className="flex items-center gap-2">
                    {selectedTicket.status !== 'in_progress' && selectedTicket.status !== 'in_review' && selectedTicket.status !== 'resolved' && (
                      <button
                        disabled={actionLoading === selectedTicket.ticket_id}
                        onClick={() => handleStartWorking(selectedTicket.ticket_id)}
                        className="px-3.5 py-2 rounded-xl bg-amber-500 text-white hover:bg-amber-600 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-50"
                      >
                        <Play className="w-3.5 h-3.5 fill-current" /> Start Working
                      </button>
                    )}

                    {selectedTicket.status !== 'resolved' && selectedTicket.status !== 'closed' && (
                      <button
                        onClick={() => openResolveModal(selectedTicket)}
                        className="px-3.5 py-2 rounded-xl bg-emerald-600 text-white hover:bg-emerald-500 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" /> Resolve
                      </button>
                    )}

                    {(selectedTicket.status === 'resolved' || selectedTicket.status === 'closed' || selectedTicket.status === 'in_progress') && (
                      <button
                        disabled={actionLoading === selectedTicket.ticket_id}
                        onClick={() => handleReopen(selectedTicket.ticket_id)}
                        className="px-3.5 py-2 rounded-xl bg-gray-100 dark:bg-white/[0.05] border border-gray-200 dark:border-white/[0.1] text-gray-800 dark:text-white/80 hover:bg-gray-200 dark:hover:bg-white/[0.1] text-xs font-medium flex items-center gap-1.5 transition-all disabled:opacity-50"
                      >
                        <RotateCcw className="w-3.5 h-3.5" /> Reopen
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="text-[11px] text-gray-400 dark:text-white/40 italic">
                    Ticket view mode · Read-only access
                  </div>
                )}

                <div className="flex items-center gap-2">
                  {isDomainManagerOrAdmin && (
                    <button
                      onClick={() => openKnowledgeUpdateModal(selectedTicket)}
                      className="px-3 py-1.5 text-xs text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-500/10 border border-violet-200 dark:border-violet-500/20 rounded-xl hover:bg-violet-100 dark:hover:bg-violet-500/20 font-medium flex items-center gap-1.5 transition-all"
                    >
                      <GitBranch className="w-3.5 h-3.5" /> Stage Knowledge Update
                    </button>
                  )}

                  <Btn variant="ghost" size="sm" onClick={() => setSelectedTicket(null)}>
                    Close
                  </Btn>
                </div>
              </div>
            </div>
          )}
        </Modal>
      )}

      {/* Resolve Ticket Modal */}
      {resolveTicketModal && (
        <Modal
          open={!!resolveTicketModal}
          onClose={() => setResolveTicketModal(null)}
          title={`Resolve Ticket — ${resolveTicketModal.ticket_id}`}
          maxWidth="max-w-2xl"
        >
          <div className="space-y-4 text-left text-xs">
            <p className="text-gray-500 dark:text-white/50">
              Provide an authoritative domain-verified resolution answer or upload a knowledge-base document to resolve ticket <span className="font-mono text-gray-800 dark:text-white/80">{resolveTicketModal.ticket_id}</span>.
            </p>

            {/* Knowledge Base File Upload & Attachment Section */}
            <div className="p-3.5 rounded-xl border border-blue-200 dark:border-blue-500/20 bg-blue-50/50 dark:bg-blue-500/5 space-y-3">
              <div className="flex items-center justify-between">
                <label className="font-semibold text-gray-800 dark:text-white/90 flex items-center gap-1.5 text-xs">
                  <Paperclip className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" /> Attached Knowledge Base Document
                </label>

                <label className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs cursor-pointer transition-all shadow-sm">
                  {uploadingAttachment ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Ingesting...
                    </>
                  ) : (
                    <>
                      <Upload className="w-3.5 h-3.5" /> Upload File (PDF/DOCX/TXT/PPTX)
                    </>
                  )}
                  <input
                    type="file"
                    accept=".pdf,.docx,.txt,.pptx,.png,.jpg,.jpeg"
                    onChange={handleUploadKBFile}
                    disabled={uploadingAttachment}
                    className="hidden"
                  />
                </label>
              </div>

              {attachmentError && (
                <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-600 dark:text-rose-400 text-xs flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{attachmentError}</span>
                </div>
              )}

              {attachments.length === 0 ? (
                <div className="text-center py-3 border border-dashed border-gray-300 dark:border-white/10 rounded-lg text-gray-400 dark:text-white/40 text-xs">
                  No knowledge-base document attached yet. Upload a document above to resolve via file ingestion.
                </div>
              ) : (
                <div className="space-y-2">
                  {attachments.map(att => {
                    const isSelected = selectedAttachmentId === att.attachment_id || attachments.length === 1
                    const isCompleted = att.status === 'COMPLETED'
                    const isProcessing = att.status === 'PENDING' || att.status === 'PROCESSING'
                    const isFailed = att.status === 'FAILED'

                    return (
                      <div
                        key={att.attachment_id}
                        onClick={() => setSelectedAttachmentId(att.attachment_id)}
                        className={`p-2.5 rounded-xl border text-left cursor-pointer transition-all flex items-center justify-between ${
                          isSelected
                            ? 'bg-white dark:bg-white/10 border-blue-500 shadow-sm ring-1 ring-blue-500/30'
                            : 'bg-white/60 dark:bg-white/[0.02] border-gray-200 dark:border-white/10 opacity-80'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <FileText className="w-4 h-4 text-blue-500 shrink-0" />
                          <div className="min-w-0">
                            <p className="font-semibold text-gray-800 dark:text-white truncate text-xs">
                              {att.original_filename}
                            </p>
                            <p className="text-[10px] text-gray-400 dark:text-white/40 font-mono">
                              ID: {att.attachment_id} • {att.file_type} {att.file_size ? `• ${(att.file_size / 1024).toFixed(1)} KB` : ''}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {isCompleted && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                              <CheckCircle2 className="w-3 h-3" /> Indexed
                            </span>
                          )}

                          {isProcessing && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 flex items-center gap-1 animate-pulse">
                              <Loader2 className="w-3 h-3 animate-spin" /> Ingesting ({att.status})
                            </span>
                          )}

                          {isFailed && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3" /> Failed
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Root Cause & Resolution Type Selection */}
            <div>
              <label className="font-semibold text-gray-800 dark:text-white/80 mb-1.5 block flex items-center gap-1.5">
                <Tag className="w-3.5 h-3.5 text-blue-500" /> Resolution Mode / Category <span className="text-rose-500">*</span>
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
                          ? 'bg-blue-50 border-blue-500 text-blue-900 dark:bg-blue-600/20 dark:border-blue-500/50 dark:text-white shadow-sm ring-1 ring-blue-500/30'
                          : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50 dark:bg-white/[0.02] dark:border-white/[0.06] dark:text-white/60'
                      }`}
                    >
                      <p className="font-semibold flex items-center justify-between text-xs">
                        <span>{info.label}</span>
                        {isSelected && <Check className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />}
                      </p>
                      <p className="text-[10px] text-gray-500 dark:text-white/40 mt-1 leading-snug">{info.description}</p>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Corrected Answer Text */}
            <div>
              <label className="font-semibold text-gray-800 dark:text-white/80 mb-1.5 block flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-emerald-500" /> Resolution Explanation / Answer
                {resolutionType !== 'FILE' && <span className="text-rose-500">*</span>}
              </label>
              <textarea
                value={correctedAnswer}
                onChange={e => setCorrectedAnswer(e.target.value)}
                rows={3}
                placeholder={resolutionType === 'FILE' ? "Optional explanation summary (auto-generated if left empty)..." : "Enter the verified authoritative resolution answer..."}
                className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500 resize-none font-sans"
              />
            </div>

            {/* Evidence & Supporting Docs */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Supporting Evidence / Explanation</label>
                <textarea
                  value={supportingEvidence}
                  onChange={e => setSupportingEvidence(e.target.value)}
                  rows={2}
                  placeholder="Explain policy or guideline source..."
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500 resize-none"
                />
              </div>

              <div>
                <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Supporting Document IDs</label>
                <input
                  type="text"
                  value={supportingDocsInput}
                  onChange={e => setSupportingDocsInput(e.target.value)}
                  placeholder="e.g. DOC_HR_2026, DOC_LEAVE_SEC_4"
                  className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500 font-mono"
                />
                <p className="text-[10px] text-gray-400 dark:text-white/30 mt-1">Comma-separated document IDs.</p>
              </div>
            </div>

            {/* Internal Notes */}
            <div>
              <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Internal Triage Notes</label>
              <input
                type="text"
                value={internalNotes}
                onChange={e => setInternalNotes(e.target.value)}
                placeholder="Internal notes for domain experts..."
                className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/30 rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500"
              />
            </div>

            {/* Status Alert for Gating */}
            {(() => {
              const activeAtt = attachments.find(a => a.attachment_id === selectedAttachmentId) || attachments[0]
              if ((resolutionType === 'FILE' || resolutionType === 'BOTH') && activeAtt) {
                if (activeAtt.status === 'PENDING' || activeAtt.status === 'PROCESSING') {
                  return (
                    <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-700 dark:text-amber-300 text-xs flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin shrink-0 text-amber-500" />
                      <span>Document processing is currently in progress. Ticket resolution is locked until document ingestion completes.</span>
                    </div>
                  )
                }
                if (activeAtt.status === 'FAILED') {
                  return (
                    <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/25 text-rose-700 dark:text-rose-300 text-xs flex items-start gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0 text-rose-500 mt-0.5" />
                      <div>
                        <p className="font-semibold">Document Ingestion Failed</p>
                        <p className="text-[11px] mt-0.5 opacity-90">{activeAtt.error_message || 'File extraction failed.'}</p>
                        <p className="text-[11px] mt-1 font-medium underline">Please re-upload a valid document above to retry resolution.</p>
                      </div>
                    </div>
                  )
                }
              }
              return null
            })()}

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-gray-200 dark:border-white/[0.06]">
              <Btn variant="ghost" size="sm" onClick={() => setResolveTicketModal(null)} disabled={resolving}>
                Cancel
              </Btn>
              <Btn
                size="sm"
                onClick={handleResolveSubmit}
                disabled={
                  resolving ||
                  (resolutionType !== 'FILE' && !correctedAnswer.trim()) ||
                  ((resolutionType === 'FILE' || resolutionType === 'BOTH') &&
                    (!attachments.length || attachments.some(a => (a.attachment_id === selectedAttachmentId || attachments.length === 1) && a.status !== 'COMPLETED')))
                }
                className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold disabled:opacity-50"
              >
                {resolving ? 'Submitting Resolution...' : 'Submit Resolution'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}

      {/* Phase 14 Knowledge Update Modal */}
      {knowledgeModalTicket && (
        <Modal
          open={!!knowledgeModalTicket}
          onClose={() => setKnowledgeModalTicket(null)}
          title="Create Knowledge Update Request (Phase 14)"
          maxWidth="max-w-xl"
        >
          <div className="space-y-4 text-left text-xs">
            <p className="text-gray-600 dark:text-white/50">
              Stage a formal Knowledge Update proposal derived from ticket <span className="font-mono text-gray-900 dark:text-white/80">{knowledgeModalTicket.ticket_id}</span>.
            </p>

            <div className="space-y-3">
              <div>
                <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Proposal Title</label>
                <input
                  type="text"
                  value={updateTitle}
                  onChange={e => setUpdateTitle(e.target.value)}
                  placeholder="e.g. Update Remote Work Equipment Reimbursement Policy"
                  className="w-full bg-gray-50 border border-gray-200 text-gray-900 placeholder:text-gray-400 dark:bg-white/[0.04] dark:border-white/[0.08] dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Root Cause</label>
                  <div className="px-3 py-2 rounded-xl bg-gray-50 border border-gray-200 dark:bg-white/[0.03] dark:border-white/[0.08] font-semibold text-gray-900 dark:text-white/90 capitalize">
                    {knowledgeModalTicket.resolution_type ? RESOLUTION_TYPE_LABELS[knowledgeModalTicket.resolution_type as ResolutionType]?.label || knowledgeModalTicket.resolution_type : 'Knowledge Missing'}
                  </div>
                </div>
                <div>
                  <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Target Document Filename</label>
                  <input
                    type="text"
                    value={updateTargetFilename}
                    onChange={e => setUpdateTargetFilename(e.target.value)}
                    placeholder="e.g. hr_remote_policy.txt"
                    className="w-full bg-gray-50 border border-gray-200 text-gray-900 placeholder:text-gray-400 dark:bg-white/[0.04] dark:border-white/[0.08] dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500 font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="font-medium text-gray-700 dark:text-white/70 mb-1 block">Proposed Knowledge / Rationale</label>
                <textarea
                  value={updateDescription}
                  onChange={e => setUpdateDescription(e.target.value)}
                  rows={4}
                  className="w-full bg-gray-50 border border-gray-200 text-gray-900 placeholder:text-gray-400 dark:bg-white/[0.04] dark:border-white/[0.08] dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-gray-200 dark:border-white/[0.06]">
              <Btn variant="ghost" size="sm" onClick={() => setKnowledgeModalTicket(null)} disabled={creatingUpdate}>
                Cancel
              </Btn>
              <Btn size="sm" onClick={handleCreateKnowledgeUpdateRequest} disabled={creatingUpdate || !updateTitle.trim()}>
                {creatingUpdate ? 'Staging Request...' : 'Submit Knowledge Update Request'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
