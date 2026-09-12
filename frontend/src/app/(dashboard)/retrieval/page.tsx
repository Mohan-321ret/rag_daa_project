'use client'
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, Search, GitBranch, Hash, Layers, Clock, ChevronRight } from 'lucide-react'
import { PageHeader, Card, ConfidenceMeter, EmptyState } from '@/components/shared/index'
import { retrievalApi, ApiError, type RetrievalRouteResponse } from '@/lib/api'

const methods = [
  { id: 'hybrid', label: 'Hybrid Retrieval', icon: <Layers className="w-4 h-4" />, color: 'from-blue-500 to-violet-500', desc: 'Combines vector + BM25 + graph for best coverage' },
  { id: 'vector', label: 'Vector Search', icon: <Zap className="w-4 h-4" />, color: 'from-blue-500 to-cyan-500', desc: 'Semantic similarity using dense embeddings' },
  { id: 'bm25', label: 'BM25 Keyword', icon: <Hash className="w-4 h-4" />, color: 'from-emerald-500 to-teal-500', desc: 'Sparse retrieval for exact keyword matching' },
  { id: 'graph', label: 'Knowledge Graph', icon: <GitBranch className="w-4 h-4" />, color: 'from-violet-500 to-purple-500', desc: 'Traverse entity relationships and concepts' },
]

const methodColors: Record<string, string> = { vector: 'text-blue-400 bg-blue-400/10', bm25: 'text-emerald-400 bg-emerald-400/10', graph: 'text-violet-400 bg-violet-400/10', hybrid: 'text-cyan-400 bg-cyan-400/10' }

export default function RetrievalPage() {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [result, setResult] = useState<RetrievalRouteResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)

  const handleRetrieve = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setError(null)
    const start = performance.now()
    try {
      const res = await retrievalApi.route(query, { top_k: topK })
      setResult(res)
      setElapsed(Math.round(performance.now() - start))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Retrieval failed')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const activeRoute = result?.route.route

  return (
    <div className="space-y-6">
      <PageHeader title="Adaptive Retrieval" description="Intelligent multi-strategy retrieval with dynamic routing" />

      {/* Query + Config */}
      <Card>
        <div className="flex gap-3 mb-4 flex-col sm:flex-row">
          <div className="flex-1 flex items-center gap-3 bg-gray-50 border border-gray-200 dark:bg-white/[0.04] dark:border-white/[0.08] rounded-xl px-4 py-3 focus-within:border-blue-500/50 transition-all">
            <Search className="w-4 h-4 text-gray-400 dark:text-white/30 flex-shrink-0" />
            <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleRetrieve()}
              placeholder="Enter query to retrieve relevant documents..."
              className="flex-1 bg-transparent text-sm text-gray-900 placeholder:text-gray-400 dark:text-white dark:placeholder:text-white/25 outline-none" />
          </div>
          <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 dark:bg-white/[0.04] dark:border-white/[0.08] rounded-xl px-3 py-2 sm:py-0">
            <span className="text-xs text-gray-500 dark:text-white/40">Top-K:</span>
            <select value={topK} onChange={e => setTopK(Number(e.target.value))} className="bg-transparent text-xs text-gray-700 dark:text-white/70 outline-none cursor-pointer">
              {[3, 5, 10, 20].map(k => <option key={k} value={k} className="bg-white text-gray-900 dark:bg-[#12121f] dark:text-white">{k}</option>)}
            </select>
          </div>
          <button onClick={handleRetrieve} disabled={!query.trim() || loading} className="flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all disabled:opacity-50 shadow-sm">
            <Zap className="w-4 h-4" /> Retrieve
          </button>
        </div>

        {/* Method Legend (informational — actual route is chosen by the backend) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {methods.map(m => (
            <div key={m.id}
              className={`p-3 rounded-xl border text-left transition-all ${activeRoute === m.id ? 'border-blue-500/40 bg-blue-500/10' : 'border-gray-200 bg-gray-50/50 dark:border-white/[0.06] dark:bg-white/[0.02]'}`}>
              <div className={`inline-flex p-1.5 rounded-lg bg-gradient-to-br ${m.color} mb-2 shadow-sm`}>
                <div className="text-white">{m.icon}</div>
              </div>
              <p className="text-xs font-semibold text-gray-900 dark:text-white/80">{m.label}</p>
              <p className="text-[10px] text-gray-500 dark:text-white/40 mt-0.5">{m.desc}</p>
              {activeRoute === m.id && <div className="mt-2 w-full h-0.5 rounded-full bg-gradient-to-r from-blue-500 to-violet-500" />}
            </div>
          ))}
        </div>
      </Card>

      {error && <Card><p className="text-sm text-red-500 dark:text-red-400 text-center py-2">{error}</p></Card>}

      {/* Router Decision */}
      {result && (
        <Card>
          <h3 className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider mb-3">Router Decision</h3>
          <div className="flex items-center gap-3 flex-wrap mb-2">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium ${methodColors[result.route.route] ?? 'bg-gray-100 text-gray-600 dark:bg-white/[0.04] dark:text-white/40'}`}>
              <ChevronRight className="w-3 h-3" />
              <span className="uppercase font-bold">{result.route.route}</span>
            </div>
            <span className="text-xs text-gray-600 dark:text-white/50">{result.route.reason}</span>
          </div>
          {result.route.signals.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {result.route.signals.map((s, i) => (
                <span key={i} className="text-[10px] bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-white/50 px-2 py-0.5 rounded-full">{s}</span>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Results */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70">{result ? `${result.results.length} Retrieved Chunks` : 'Results'}</h3>
          {elapsed !== null && (
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-white/40">
              <Clock className="w-3.5 h-3.5" />
              <span>{elapsed}ms round-trip</span>
            </div>
          )}
        </div>

        <AnimatePresence>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="flex items-center gap-3 text-gray-500 dark:text-white/50">
                <Zap className="w-5 h-5 animate-pulse text-blue-500" />
                <span className="text-sm">Retrieving documents...</span>
              </div>
            </div>
          ) : !result ? (
            <Card><EmptyState icon={<Search className="w-5 h-5" />} title="No query run yet" description="Enter a query above and click Retrieve to see results." /></Card>
          ) : result.results.map((r, i) => (
            <motion.div key={`${r.document_id}-${r.chunk_index}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}
              className="p-4 rounded-2xl bg-white border border-gray-200/80 dark:bg-white/[0.03] dark:border-white/[0.07] dark:hover:border-white/[0.12] shadow-sm dark:shadow-none transition-all">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[11px] font-bold text-gray-400 dark:text-white/30">#{i + 1}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase ${methodColors[r.source] ?? 'text-gray-600 bg-gray-100 dark:text-white/50 dark:bg-white/[0.06]'}`}>{r.source}</span>
                  <span className="text-[11px] text-gray-500 dark:text-white/50 truncate max-w-[200px]">{r.document_id} · chunk {r.chunk_index}</span>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <div className="w-24">
                    <ConfidenceMeter value={r.score} size="sm" />
                  </div>
                </div>
              </div>
              <p className="text-xs text-gray-700 dark:text-white/60 leading-relaxed">{r.text_preview}</p>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}
