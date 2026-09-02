'use client'
import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { ArrowLeft, AlertTriangle, CheckCircle, Copy, Download } from 'lucide-react'
import { PageHeader } from '@/components/shared/index'
import { formatDateTime, formatLatency } from '@/lib/utils'
import { queryLogsApi } from '@/lib/api'
import type { QueryLogDetail } from '@/types'
import Link from 'next/link'

export default function QueryLogDetailPage() {
  const params = useParams()
  const router = useRouter()
  const queryId = params.queryId as string
  
  const [log, setLog] = useState<QueryLogDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [canViewSensitive, setCanViewSensitive] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    loadQueryLog()
  }, [queryId])

  const loadQueryLog = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await queryLogsApi.get(queryId)
      setLog(response.log)
      setCanViewSensitive(response.can_view_sensitive)
    } catch (err: any) {
      setError(err.message || 'Failed to load query log')
      console.error('Failed to load query log:', err)
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  const downloadAsJson = () => {
    if (!log) return
    const dataStr = JSON.stringify(log, null, 2)
    const dataBlob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(dataBlob)
    const link = document.createElement('a')
    link.href = url
    link.download = `query-${log.query_id}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Link href="/query-history">
            <button className="flex items-center gap-2 text-white/60 hover:text-white transition-colors">
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          </Link>
        </div>
        <div className="text-center py-12 text-white/40">Loading query log...</div>
      </div>
    )
  }

  if (error || !log) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Link href="/query-history">
            <button className="flex items-center gap-2 text-white/60 hover:text-white transition-colors">
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          </Link>
        </div>
        <div className="text-center py-12">
          <p className="text-red-400 font-medium">{error || 'Query log not found'}</p>
        </div>
      </div>
    )
  }

  const methodColors: Record<string, string> = {
    hybrid: 'bg-blue-500/20 text-blue-400',
    vector: 'bg-violet-500/20 text-violet-400',
    bm25: 'bg-emerald-500/20 text-emerald-400',
    graph: 'bg-cyan-500/20 text-cyan-400',
  }

  const verificationColors: Record<string, string> = {
    verified: 'bg-emerald-500/20 text-emerald-400',
    partial: 'bg-yellow-500/20 text-yellow-400',
    unverified: 'bg-gray-500/20 text-gray-400',
    failed: 'bg-red-500/20 text-red-400',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/query-history">
            <button className="flex items-center gap-2 text-white/60 hover:text-white transition-colors">
              <ArrowLeft className="w-4 h-4" />
              Back to Query History
            </button>
          </Link>
        </div>
        <button
          onClick={downloadAsJson}
          className="flex items-center gap-2 px-4 py-2 bg-white/[0.05] border border-white/[0.07] rounded-lg text-xs text-white hover:bg-white/[0.08] transition-colors"
        >
          <Download className="w-3.5 h-3.5" />
          Export JSON
        </button>
      </div>

      {/* Query Info Card */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
      >
        <div className="flex items-start gap-4 mb-4">
          <div className="flex-shrink-0">
            {log.hallucinations_detected > 0 ? (
              <AlertTriangle className="w-6 h-6 text-red-400" />
            ) : (
              <CheckCircle className="w-6 h-6 text-emerald-400" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs text-white/40">{log.query_id}</span>
              <button
                onClick={() => copyToClipboard(log.query_id, 'queryId')}
                className="text-white/30 hover:text-white/60 transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-base font-medium text-white mb-4">{log.query_text}</p>

            <div className="flex flex-wrap gap-2 mb-4">
              {log.intent && (
                <span className="px-3 py-1 bg-blue-500/20 text-blue-400 text-xs rounded-full">
                  Intent: {log.intent}
                </span>
              )}
              {log.route && (
                <span className={`px-3 py-1 text-xs rounded-full ${methodColors[log.route as keyof typeof methodColors]}`}>
                  Route: {log.route}
                </span>
              )}
              {log.verification_result && (
                <span className={`px-3 py-1 text-xs rounded-full ${verificationColors[log.verification_result as keyof typeof verificationColors]}`}>
                  Verification: {log.verification_result}
                </span>
              )}
              {log.was_rewritten && (
                <span className="px-3 py-1 bg-yellow-500/20 text-yellow-400 text-xs rounded-full">
                  Rewritten
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 text-xs text-white/40">
              <span>{formatDateTime(log.created_at)}</span>
              {log.user_id && <span>User: {log.user_id}</span>}
              {log.user_role && <span>Role: {log.user_role}</span>}
              {log.user_domain && <span>Domain: {log.user_domain}</span>}
            </div>
          </div>
        </div>
      </motion.div>

      {/* Answer Section */}
      {log.answer_text && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-3">Answer</h3>
          <p className="text-sm text-white/70 whitespace-pre-wrap">{log.answer_text}</p>
        </motion.div>
      )}

      {/* Performance Metrics */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="grid grid-cols-1 md:grid-cols-4 gap-4"
      >
        {[
          { label: 'Total Latency', value: log.latency_ms ? formatLatency(log.latency_ms) : 'N/A', color: 'text-blue-400' },
          { label: 'Retrieval Latency', value: log.retrieval_latency_ms ? formatLatency(log.retrieval_latency_ms) : 'N/A', color: 'text-violet-400' },
          { label: 'Reranking Latency', value: log.reranking_latency_ms ? formatLatency(log.reranking_latency_ms) : 'N/A', color: 'text-cyan-400' },
          { label: 'LLM Latency', value: log.llm_latency_ms ? formatLatency(log.llm_latency_ms) : 'N/A', color: 'text-emerald-400' },
        ].map((m) => (
          <div key={m.label} className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-4">
            <p className={`text-lg font-bold ${m.color}`}>{m.value}</p>
            <p className="text-[11px] text-white/40 mt-1">{m.label}</p>
          </div>
        ))}
      </motion.div>

      {/* Retrieval & Scores */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-4">Retrieval Details</h3>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-white/40 mb-1">Retrieved Chunks</p>
              <p className="text-lg font-semibold text-white">{log.retrieved_chunks}</p>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Authorized Chunks</p>
              <p className="text-lg font-semibold text-white">{log.authorized_chunk_ids.length}</p>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Retrieval Score</p>
              <p className="text-lg font-semibold text-white">
                {log.retrieval_score !== undefined ? log.retrieval_score.toFixed(3) : 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Reranking Score</p>
              <p className="text-lg font-semibold text-white">
                {log.reranking_score !== undefined ? log.reranking_score.toFixed(3) : 'N/A'}
              </p>
            </div>
            {log.retrieval_strategy && (
              <div>
                <p className="text-xs text-white/40 mb-1">Strategy</p>
                <p className="text-sm text-white capitalize">{log.retrieval_strategy}</p>
              </div>
            )}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-4">Verification & Quality</h3>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-white/40 mb-1">Confidence Score</p>
              <div className="flex items-center gap-2">
                <p className="text-lg font-semibold text-white">
                  {log.confidence_score !== undefined ? (log.confidence_score * 100).toFixed(1) : 'N/A'}%
                </p>
                {log.confidence_score !== undefined && (
                  <div className="flex-1 bg-white/[0.05] rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full"
                      style={{ width: `${log.confidence_score * 100}%` }}
                    />
                  </div>
                )}
              </div>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Hallucinations Detected</p>
              <p className={`text-lg font-semibold ${log.hallucinations_detected > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                {log.hallucinations_detected}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Citations</p>
              <p className="text-lg font-semibold text-white">{log.citation_count}</p>
            </div>
            <div>
              <p className="text-xs text-white/40 mb-1">Grounded</p>
              <p className={`text-sm font-semibold ${log.is_grounded ? 'text-emerald-400' : 'text-gray-400'}`}>
                {log.is_grounded ? 'Yes' : log.is_grounded === false ? 'No' : 'Unknown'}
              </p>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Chunk Details */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
      >
        <h3 className="text-sm font-semibold text-white mb-4">Chunk Information</h3>
        <div className="space-y-4">
          {log.retrieved_chunk_ids.length > 0 && (
            <div>
              <p className="text-xs text-white/40 mb-2">Retrieved Chunk IDs</p>
              <div className="flex flex-wrap gap-2">
                {log.retrieved_chunk_ids.map(id => (
                  <span key={id} className="text-xs bg-blue-500/20 text-blue-400 px-2 py-1 rounded">
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}
          {log.authorized_chunk_ids.length > 0 && (
            <div>
              <p className="text-xs text-white/40 mb-2">Authorized Chunk IDs</p>
              <div className="flex flex-wrap gap-2">
                {log.authorized_chunk_ids.map(id => (
                  <span key={id} className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded">
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </motion.div>

      {/* Verification Details */}
      {log.verification_details && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-3">Verification Details</h3>
          <p className="text-sm text-white/70 whitespace-pre-wrap">{log.verification_details}</p>
        </motion.div>
      )}

      {/* Reranking Explanation */}
      {log.reranking_explanation && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-3">Reranking Explanation</h3>
          <p className="text-sm text-white/70 whitespace-pre-wrap">{log.reranking_explanation}</p>
        </motion.div>
      )}

      {/* Ticket Information */}
      {log.ticket_id && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-3">Associated Ticket</h3>
          <div className="space-y-2">
            <div>
              <p className="text-xs text-white/40 mb-1">Ticket ID</p>
              <p className="text-sm text-white font-mono">{log.ticket_id}</p>
            </div>
            {log.ticket_status && (
              <div>
                <p className="text-xs text-white/40 mb-1">Status</p>
                <p className="text-sm text-white capitalize">{log.ticket_status}</p>
              </div>
            )}
          </div>
        </motion.div>
      )}

      {/* Sensitive Fields (if authorized) */}
      {canViewSensitive && log.chunk_access_violations > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7 }}
          className="bg-red-500/10 border border-red-500/20 rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-red-400 mb-3">⚠️ Access Violations (Sensitive)</h3>
          <div className="space-y-2">
            <div>
              <p className="text-xs text-white/40 mb-1">Unauthorized Chunk Access Attempts</p>
              <p className="text-lg font-semibold text-red-400">{log.chunk_access_violations}</p>
            </div>
            {log.access_violation_details && (
              <div>
                <p className="text-xs text-white/40 mb-1">Details</p>
                <p className="text-sm text-red-300/70 whitespace-pre-wrap font-mono text-xs">
                  {log.access_violation_details}
                </p>
              </div>
            )}
          </div>
        </motion.div>
      )}

      {/* Model Information */}
      {log.model_used && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8 }}
          className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-white mb-3">Model Information</h3>
          <p className="text-sm text-white">{log.model_used}</p>
        </motion.div>
      )}
    </div>
  )
}
