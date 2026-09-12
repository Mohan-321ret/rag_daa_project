'use client'
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Sparkles, ChevronRight, Tag, Clock, Brain, Zap } from 'lucide-react'
import { PageHeader, Card } from '@/components/shared/index'
import { queryIntelligenceApi, ApiError, type QueryAnalysisResponse } from '@/lib/api'

const exampleQueries = [
  'What were the key financial highlights from Q4 2024?',
  'Compare customer satisfaction across departments',
  'What are the compliance requirements for data handling?',
  'Summarize the product roadmap for H1 2025',
]

export default function QueryIntelligencePage() {
  const [query, setQuery] = useState('')
  const [parsed, setParsed] = useState<QueryAnalysisResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAnalyze = async (q: string) => {
    setQuery(q)
    setLoading(true)
    setError(null)
    try {
      const res = await queryIntelligenceApi.analyze(q)
      setParsed(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Analysis failed')
      setParsed(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Query Intelligence" description="Analyze, parse, and expand queries with AI-powered understanding" />

      {/* Query Input */}
      <Card>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 flex items-center gap-3 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-4 py-3 focus-within:border-blue-500/50 transition-all">
            <Search className="w-4 h-4 text-gray-400 dark:text-white/30 flex-shrink-0" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && query && handleAnalyze(query)}
              placeholder="Enter your query to analyze intent, entities, and complexity..."
              className="flex-1 bg-transparent text-sm text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none"
            />
          </div>
          <motion.button
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
            onClick={() => query && handleAnalyze(query)}
            className="flex items-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all shadow-sm"
          >
            <Sparkles className="w-4 h-4" /> Analyze
          </motion.button>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-medium text-gray-500 dark:text-white/30">Try:</span>
          {exampleQueries.map(q => (
            <button key={q} onClick={() => handleAnalyze(q)}
              className="text-[11px] font-medium text-blue-700 dark:text-blue-400/90 hover:text-blue-800 dark:hover:text-blue-300 bg-blue-50 dark:bg-blue-500/10 hover:bg-blue-100 dark:hover:bg-blue-500/15 border border-blue-200 dark:border-blue-500/20 px-3 py-1 rounded-full transition-all truncate max-w-[240px]">
              {q}
            </button>
          ))}
        </div>
      </Card>

      {error && <Card><p className="text-sm text-red-500 dark:text-red-400 text-center py-2">{error}</p></Card>}

      {/* Analysis Results */}
      <AnimatePresence>
        {loading && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center justify-center py-12">
            <div className="flex items-center gap-3 text-gray-500 dark:text-white/50">
              <Brain className="w-5 h-5 animate-pulse text-blue-600 dark:text-blue-400" />
              <span className="text-sm font-medium">Analyzing query intelligence...</span>
            </div>
          </motion.div>
        )}

        {parsed && !loading && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Intent */}
            <Card hover>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-8 h-8 rounded-lg bg-blue-50 dark:bg-blue-500/15 flex items-center justify-center">
                  <Brain className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                </div>
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Intent</span>
              </div>
              <p className="text-lg font-bold text-gray-900 dark:text-white capitalize">{parsed.intent.intent.replace(/_/g, ' ')}</p>
              <p className="text-xs text-gray-500 dark:text-white/40 mt-1">{(parsed.intent.confidence * 100).toFixed(0)}% confidence · {parsed.intent.method}</p>
            </Card>

            {/* Complexity */}
            <Card hover>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-8 h-8 rounded-lg bg-violet-50 dark:bg-violet-500/15 flex items-center justify-center">
                  <Zap className="w-4 h-4 text-violet-600 dark:text-violet-400" />
                </div>
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Complexity</span>
              </div>
              <p className="text-lg font-bold text-gray-900 dark:text-white capitalize">{parsed.complexity.level}</p>
              <div className="mt-2 h-1.5 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden">
                <motion.div initial={{ width: 0 }} animate={{ width: `${Math.min(parsed.complexity.score * 10, 100)}%` }}
                  transition={{ duration: 0.8 }} className="h-full rounded-full bg-gradient-to-r from-violet-500 to-blue-500" />
              </div>
              <p className="text-[10px] text-gray-400 dark:text-white/30 mt-1">suggested top-k: {parsed.suggested_top_k}</p>
            </Card>

            {/* Temporal */}
            <Card hover>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-8 h-8 rounded-lg bg-cyan-50 dark:bg-cyan-500/15 flex items-center justify-center">
                  <Clock className="w-4 h-4 text-cyan-600 dark:text-cyan-400" />
                </div>
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Temporal</span>
              </div>
              <p className="text-lg font-bold text-gray-900 dark:text-white capitalize">{parsed.temporal.scope.replace(/_/g, ' ')}</p>
              <p className="text-xs text-gray-500 dark:text-white/40 mt-1">{parsed.temporal.expressions.join(', ') || 'No time expressions detected'}</p>
            </Card>

            {/* Entities */}
            <Card hover className="md:col-span-2">
              <div className="flex items-center gap-2 mb-3">
                <Tag className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Extracted Entities</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {parsed.entities.length === 0 && <span className="text-xs text-gray-400 dark:text-white/30">No entities detected</span>}
                {parsed.entities.map((e, i) => (
                  <span key={i} className="text-xs font-medium bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20 px-3 py-1 rounded-full">{e.text} <span className="text-emerald-600/70 dark:text-emerald-400/50">({e.label})</span></span>
                ))}
              </div>
            </Card>

            {/* Sub-queries */}
            <Card hover>
              <div className="flex items-center gap-2 mb-3">
                <ChevronRight className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Sub-Queries</span>
              </div>
              <div className="space-y-2">
                {parsed.sub_questions.length === 0 && <p className="text-[11px] text-gray-400 dark:text-white/30">No decomposition needed</p>}
                {parsed.sub_questions.map((sq, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="text-[10px] font-bold bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-500/20 px-1.5 py-0.5 rounded mt-0.5 flex-shrink-0">{i + 1}</span>
                    <p className="text-[11px] text-gray-700 dark:text-white/60">{sq}</p>
                  </div>
                ))}
              </div>
            </Card>

            {/* Normalized Query */}
            <Card className="md:col-span-3">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                <span className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider">Normalized Query</span>
              </div>
              <p className="text-sm text-gray-800 dark:text-white/70 leading-relaxed bg-gray-50 dark:bg-white/[0.03] rounded-xl p-4 border border-gray-200 dark:border-white/[0.05]">{parsed.normalized_query}</p>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
