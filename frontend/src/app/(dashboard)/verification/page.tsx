'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, AlertTriangle, CheckCircle, XCircle, BookOpen, Sparkles } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '@/components/shared/index'
import { verificationApi, ApiError, type ClaimVerificationOut, type VerifyResponse } from '@/lib/api'

function statusIcon(status: string) {
  if (status === 'contradicted') return <XCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
  if (status === 'supported') return <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
  return <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
}

export default function VerificationPage() {
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<VerifyResponse | null>(null)
  const [selected, setSelected] = useState<ClaimVerificationOut | null>(null)
  const [filter, setFilter] = useState<'all' | 'supported' | 'contradicted'>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleVerify = async () => {
    if (!answer.trim() || loading) return
    setLoading(true)
    setError(null)
    try {
      const res = await verificationApi.verify(answer)
      setResult(res)
      setSelected(res.verifications[0] ?? null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const filtered = (result?.verifications ?? []).filter(c => {
    if (filter === 'supported') return c.status === 'supported'
    if (filter === 'contradicted') return c.status === 'contradicted'
    return true
  })

  const trust = result?.confidence_score ?? 0

  return (
    <div className="space-y-6">
      <PageHeader title="Evidence Verification" description="Automated fact-checking, hallucination detection, and citation validation" />

      {/* Input */}
      <Card>
        <div className="flex gap-3">
          <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={3}
            placeholder="Paste an answer/claim text to independently fact-check it against the knowledge base..."
            className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/25 outline-none focus:border-blue-500/50 transition-all resize-none" />
          <button onClick={handleVerify} disabled={!answer.trim() || loading}
            className="flex items-center gap-2 px-5 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all disabled:opacity-50 self-stretch">
            <Sparkles className="w-4 h-4" /> Verify
          </button>
        </div>
      </Card>

      {error && <Card><p className="text-sm text-red-400 text-center py-2">{error}</p></Card>}

      {loading && (
        <Card>
          <div className="flex items-center justify-center py-12">
            <div className="flex items-center gap-3 text-white/50">
              <ShieldCheck className="w-5 h-5 animate-pulse text-blue-400" />
              <span className="text-sm">Extracting and checking claims against evidence...</span>
            </div>
          </div>
        </Card>
      )}

      {!result && !loading && (
        <Card><EmptyState icon={<ShieldCheck className="w-5 h-5" />} title="No verification run yet" description="Paste an answer above to extract its claims and check them against the knowledge base." /></Card>
      )}

      {result && !loading && (
        <>
          {/* Trust Score Banner */}
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
            className={`p-5 rounded-2xl border ${trust >= 0.8 ? 'bg-emerald-500/10 border-emerald-500/20' : trust >= 0.6 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <ShieldCheck className={`w-6 h-6 ${trust >= 0.8 ? 'text-emerald-400' : trust >= 0.6 ? 'text-amber-400' : 'text-red-400'}`} />
                <div>
                  <p className="text-sm font-bold text-white">Overall Confidence Score</p>
                  <p className="text-xs text-white/50">{result.claims_checked}/{result.claims_total} claims checked · {result.hallucinations.length} flagged</p>
                </div>
              </div>
              <div className="text-right">
                <p className={`text-3xl font-bold ${trust >= 0.8 ? 'text-emerald-400' : trust >= 0.6 ? 'text-amber-400' : 'text-red-400'}`}>{(trust * 100).toFixed(0)}%</p>
                {result.was_rewritten && <p className="text-xs text-amber-400/70">Answer was corrected</p>}
              </div>
            </div>
            <div className="mt-3 h-2 bg-white/[0.06] rounded-full overflow-hidden">
              <motion.div initial={{ width: 0 }} animate={{ width: `${trust * 100}%` }} transition={{ duration: 1 }}
                className={`h-full rounded-full ${trust >= 0.8 ? 'bg-emerald-500' : trust >= 0.6 ? 'bg-amber-500' : 'bg-red-500'}`} />
            </div>
          </motion.div>

          {result.was_rewritten && (
            <Card>
              <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Final (Corrected) Answer</h3>
              <p className="text-sm text-white/70 leading-relaxed bg-white/[0.03] rounded-xl p-4 border border-white/[0.05]">{result.final_answer}</p>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Claims List */}
            <div className="lg:col-span-1 space-y-3">
              <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1">
                {(['all', 'supported', 'contradicted'] as const).map(f => (
                  <button key={f} onClick={() => setFilter(f)}
                    className={`flex-1 py-1.5 rounded-lg text-[11px] font-medium capitalize transition-all ${filter === f ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                    {f}
                  </button>
                ))}
              </div>
              {filtered.length === 0 && <p className="text-xs text-white/30 text-center py-6">No claims in this category.</p>}
              {filtered.map((claim, i) => (
                <motion.button key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                  onClick={() => setSelected(claim)}
                  className={`w-full p-3 rounded-xl border text-left transition-all ${selected === claim ? 'border-blue-500/30 bg-blue-500/10' : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12]'}`}>
                  <div className="flex items-start gap-2">
                    {statusIcon(claim.status)}
                    <div className="flex-1">
                      <p className="text-[11px] text-white/70 leading-tight">{claim.claim}</p>
                      <p className="text-[10px] text-white/30 mt-1">similarity: {(claim.statement_similarity * 100).toFixed(0)}%</p>
                    </div>
                  </div>
                </motion.button>
              ))}
            </div>

            {/* Detail Panel */}
            <div className="lg:col-span-2 space-y-4">
              {selected ? (
                <Card>
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium capitalize ${selected.status === 'contradicted' ? 'bg-red-500/20 text-red-400' : selected.status === 'supported' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                        {selected.status === 'contradicted' ? '⚠️ Contradicted' : selected.status === 'supported' ? '✓ Supported' : '? Unverifiable'}
                      </span>
                      <p className="text-sm font-semibold text-white mt-2">{selected.claim}</p>
                    </div>
                  </div>

                  <div className="mb-4">
                    <p className="text-xs text-white/40 mb-2">Statement Similarity</p>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 h-3 bg-white/[0.06] rounded-full overflow-hidden">
                        <motion.div initial={{ width: 0 }} animate={{ width: `${selected.statement_similarity * 100}%` }} transition={{ duration: 0.8 }}
                          className={`h-full rounded-full ${selected.statement_similarity >= 0.8 ? 'bg-gradient-to-r from-emerald-500 to-emerald-400' : selected.statement_similarity >= 0.5 ? 'bg-gradient-to-r from-amber-500 to-amber-400' : 'bg-gradient-to-r from-red-500 to-red-400'}`} />
                      </div>
                      <span className="text-lg font-bold text-white/80">{(selected.statement_similarity * 100).toFixed(0)}%</span>
                    </div>
                  </div>

                  {selected.status === 'contradicted' && (
                    <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 mb-4">
                      <div className="flex items-center gap-2 mb-1">
                        <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                        <span className="text-xs font-semibold text-red-400">Contradiction Detected</span>
                      </div>
                      <p className="text-xs text-red-300/70">
                        Claim values {selected.claim_values.join(', ') || '—'} do not match evidence values {selected.evidence_values.join(', ') || '—'}.
                      </p>
                    </div>
                  )}

                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <BookOpen className="w-3.5 h-3.5 text-blue-400" />
                      <p className="text-xs font-semibold text-white/50">Evidence</p>
                    </div>
                    {selected.evidence_text ? (
                      <div className="flex items-start gap-2 p-2.5 rounded-xl bg-white/[0.03] border border-white/[0.05]">
                        <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded font-mono">{selected.evidence_document_id}</span>
                        <p className="text-xs text-white/60">{selected.evidence_text}</p>
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-400 ml-auto flex-shrink-0" />
                      </div>
                    ) : (
                      <div className="p-3 rounded-xl bg-red-500/5 border border-red-500/15 text-xs text-red-400/70">
                        No supporting evidence found in knowledge base
                      </div>
                    )}
                  </div>
                </Card>
              ) : (
                <Card><EmptyState icon={<BookOpen className="w-5 h-5" />} title="Select a claim" /></Card>
              )}

              {/* Summary Stats */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Supported', value: result.verifications.filter(c => c.status === 'supported').length, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
                  { label: 'Contradicted', value: result.hallucinations.length, color: 'text-red-400', bg: 'bg-red-500/10' },
                  { label: 'Avg Similarity', value: `${(result.verifications.reduce((s, c) => s + c.statement_similarity, 0) / (result.verifications.length || 1) * 100).toFixed(0)}%`, color: 'text-blue-400', bg: 'bg-blue-500/10' },
                ].map(s => (
                  <div key={s.label} className={`${s.bg} rounded-2xl p-4 text-center`}>
                    <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                    <p className="text-[11px] text-white/40 mt-1">{s.label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
