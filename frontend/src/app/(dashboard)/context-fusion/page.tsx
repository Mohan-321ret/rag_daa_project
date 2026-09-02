'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Layers, Copy, CheckCircle, Search, Zap } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '@/components/shared/index'
import { ConfidenceMeter } from '@/components/shared/index'
import { contextFusionApi, ApiError, type ContextFuseResponse } from '@/lib/api'

export default function ContextFusionPage() {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<ContextFuseResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleFuse = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setError(null)
    try {
      const res = await contextFusionApi.fuse(query)
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Context fusion failed')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Context Fusion" description="Intelligent context assembly, deduplication, and compression pipeline" />

      <Card>
        <div className="flex gap-3">
          <div className="flex-1 flex items-center gap-3 bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 focus-within:border-blue-500/50 transition-all">
            <Search className="w-4 h-4 text-white/30 flex-shrink-0" />
            <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleFuse()}
              placeholder="Enter a query to run through the fusion pipeline..."
              className="flex-1 bg-transparent text-sm text-white placeholder:text-white/25 outline-none" />
          </div>
          <button onClick={handleFuse} disabled={!query.trim() || loading} className="flex items-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all disabled:opacity-50">
            <Zap className="w-4 h-4" /> Fuse Context
          </button>
        </div>
      </Card>

      {error && <Card><p className="text-sm text-red-400 text-center py-2">{error}</p></Card>}

      {loading && (
        <Card>
          <div className="flex items-center justify-center py-12">
            <div className="flex items-center gap-3 text-white/50">
              <Layers className="w-5 h-5 animate-pulse text-blue-400" />
              <span className="text-sm">Deduplicating, ranking, and compressing context...</span>
            </div>
          </div>
        </Card>
      )}

      {!result && !loading && (
        <Card><EmptyState icon={<Layers className="w-5 h-5" />} title="No fusion run yet" description="Enter a query above to see how retrieved chunks are deduplicated, reranked, and compressed." /></Card>
      )}

      {result && !loading && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Chunks Panel */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white/70">Fused Chunks</h3>
              <span className="text-xs text-white/40">{result.chunks.length} chunks</span>
            </div>
            {result.chunks.map((chunk, i) => {
              const compressed = chunk.compressed_char_count != null && chunk.original_char_count != null && chunk.compressed_char_count < chunk.original_char_count
              return (
                <motion.div key={`${chunk.document_id}-${chunk.chunk_index}`} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                  className={`p-3 rounded-xl border transition-all ${compressed ? 'border-amber-500/20 bg-amber-500/5' : 'border-white/[0.07] bg-white/[0.03]'}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-white/30 font-mono">#{i + 1}</span>
                      <span className="text-[10px] text-white/50 truncate max-w-[140px]">{chunk.document_id} · chunk {chunk.chunk_index}</span>
                      {compressed && <span className="text-[10px] bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded-full">Compressed</span>}
                    </div>
                    <div className="w-16"><ConfidenceMeter value={chunk.score} size="sm" /></div>
                  </div>
                  <p className="text-[11px] leading-relaxed text-white/60">{chunk.text}</p>
                </motion.div>
              )
            })}
            {result.chunks.length === 0 && <p className="text-xs text-white/30 text-center py-6">No chunks survived the fusion pipeline.</p>}
          </div>

          {/* Final Context */}
          <div className="space-y-4">
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-white/70">Fusion Statistics</h3>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Input Chunks', value: result.stats.chunks_in },
                  { label: 'After Dedup', value: result.stats.chunks_after_dedup },
                  { label: 'Duplicates Removed', value: result.stats.duplicates_removed },
                  { label: 'Dropped for Budget', value: result.stats.chunks_dropped_for_budget },
                  { label: 'Output Chunks', value: result.stats.chunks_out },
                  { label: 'Compression Ratio', value: `${(result.stats.compression_ratio * 100).toFixed(0)}%` },
                ].map(s => (
                  <div key={s.label} className="bg-white/[0.03] rounded-xl p-3 text-center">
                    <p className="text-lg font-bold text-white">{s.value}</p>
                    <p className="text-[10px] text-white/30">{s.label}</p>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-white/70">Final Context Window</h3>
                </div>
                <button onClick={() => navigator.clipboard.writeText(result.optimized_context)} className="text-white/30 hover:text-white/60 transition-colors"><Copy className="w-3.5 h-3.5" /></button>
              </div>
              <div className="bg-[#0a0a14] rounded-xl p-4 font-mono text-[11px] text-white/60 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
                {result.optimized_context || 'Empty context window.'}
              </div>
              <div className="mt-3 flex items-center justify-between text-[11px] text-white/40">
                <span>{result.stats.chars_in.toLocaleString()} → {result.stats.chars_out.toLocaleString()} chars</span>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
