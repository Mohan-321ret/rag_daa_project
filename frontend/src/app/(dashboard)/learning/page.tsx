'use client'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { TrendingUp, ThumbsUp, MessageSquare, Target, BarChart2, AlertTriangle } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '@/components/shared/index'
import { feedbackApi, ApiError } from '@/lib/api'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

const windows = [7, 30, 90]

export default function LearningPage() {
  const [windowDays, setWindowDays] = useState(30)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['feedback-metrics', windowDays],
    queryFn: () => feedbackApi.metrics(windowDays),
  })

  const routeData = data
    ? Object.entries(data.queries_by_route).map(([route, count]) => ({
        route,
        count,
        accuracy: data.retrieval_accuracy_by_route[route] ?? 0,
        samples: data.samples_by_route[route] ?? 0,
      }))
    : []

  return (
    <div className="space-y-6">
      <PageHeader title="Continuous Learning" description="Feedback-driven performance metrics and routing improvement">
        <div className="flex items-center gap-1 bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 shadow-sm dark:shadow-none">
          {windows.map(w => (
            <button key={w} onClick={() => setWindowDays(w)}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all ${windowDays === w ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-600 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'}`}>
              {w}d
            </button>
          ))}
        </div>
      </PageHeader>

      {isError && <Card><p className="text-sm text-red-600 dark:text-red-400 font-medium text-center py-4">{error instanceof ApiError ? error.message : 'Failed to load metrics'}</p></Card>}

      {!isError && !isLoading && data && data.total_queries === 0 && (
        <Card><EmptyState icon={<TrendingUp className="w-5 h-5" />} title="No queries logged yet" description="Ask questions on the Enterprise LLM page and rate the answers to populate these metrics." /></Card>
      )}

      {data && data.total_queries > 0 && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'User Satisfaction', value: data.user_satisfaction != null ? `${(data.user_satisfaction * 100).toFixed(0)}%` : '—', icon: <ThumbsUp className="w-4 h-4" />, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50/80 dark:bg-amber-500/10 border border-amber-200/80 dark:border-transparent shadow-sm dark:shadow-none' },
              { label: 'Total Queries', value: data.total_queries, icon: <MessageSquare className="w-4 h-4" />, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50/80 dark:bg-blue-500/10 border border-blue-200/80 dark:border-transparent shadow-sm dark:shadow-none' },
              { label: 'Rated Queries', value: data.total_rated, icon: <Target className="w-4 h-4" />, color: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-50/80 dark:bg-violet-500/10 border border-violet-200/80 dark:border-transparent shadow-sm dark:shadow-none' },
              { label: 'Hallucination Rate', value: data.hallucination_rate != null ? `${(data.hallucination_rate * 100).toFixed(1)}%` : '—', icon: <AlertTriangle className="w-4 h-4" />, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50/80 dark:bg-red-500/10 border border-red-200/80 dark:border-transparent shadow-sm dark:shadow-none' },
            ].map((s, i) => (
              <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                className={`${s.bg} rounded-2xl p-4 flex items-center gap-3`}>
                <div className={s.color}>{s.icon}</div>
                <div>
                  <p className="text-xl font-bold text-gray-900 dark:text-white">{s.value}</p>
                  <p className="text-[11px] text-gray-600 dark:text-white/50 font-medium">{s.label}</p>
                </div>
              </motion.div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Latency */}
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                <h3 className="text-sm font-semibold text-gray-800 dark:text-white/80">Latency</h3>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 dark:bg-white/[0.03] rounded-xl p-4 text-center border border-gray-200/80 dark:border-transparent">
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">{data.avg_latency_ms ? Math.round(data.avg_latency_ms) : '—'}ms</p>
                  <p className="text-[11px] text-gray-600 dark:text-white/50 font-medium mt-1">Average</p>
                </div>
                <div className="bg-gray-50 dark:bg-white/[0.03] rounded-xl p-4 text-center border border-gray-200/80 dark:border-transparent">
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">{data.p95_latency_ms ? Math.round(data.p95_latency_ms) : '—'}ms</p>
                  <p className="text-[11px] text-gray-600 dark:text-white/50 font-medium mt-1">P95</p>
                </div>
              </div>
            </Card>

            {/* Queries by route */}
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <h3 className="text-sm font-semibold text-gray-800 dark:text-white/80">Queries by Retrieval Route</h3>
              </div>
              {routeData.length === 0 ? <p className="text-xs text-gray-500 dark:text-white/40 font-medium">No route data yet</p> : (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={routeData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-gray-200 dark:text-white/[0.06]" />
                    <XAxis dataKey="route" tick={{ fill: 'currentColor', fontSize: 10 }} className="text-gray-600 dark:text-white/50" axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: 'currentColor', fontSize: 10 }} className="text-gray-600 dark:text-white/50" axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'var(--card-bg, #ffffff)', border: '1px solid var(--card-border, #e2e8f0)', borderRadius: 12, color: 'var(--text-primary, #0f172a)' }} />
                    <Bar dataKey="count" name="Queries" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          {/* Retrieval accuracy by route */}
          <Card>
            <div className="flex items-center gap-2 mb-4">
              <Target className="w-4 h-4 text-violet-600 dark:text-violet-400" />
              <h3 className="text-sm font-semibold text-gray-800 dark:text-white/80">Retrieval Accuracy by Route (👍 share of rated queries)</h3>
            </div>
            <div className="space-y-3">
              {routeData.map(r => (
                <div key={r.route}>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-gray-800 dark:text-white/70 uppercase font-semibold">{r.route}</span>
                    <span className="text-gray-600 dark:text-white/50 font-medium">{r.accuracy != null ? `${(r.accuracy * 100).toFixed(0)}%` : '—'} · {r.samples} samples</span>
                  </div>
                  <div className="h-1.5 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${(r.accuracy ?? 0) * 100}%` }} transition={{ duration: 0.8 }}
                      className="h-full rounded-full bg-gradient-to-r from-violet-500 to-blue-500" />
                  </div>
                </div>
              ))}
              {routeData.length === 0 && <p className="text-xs text-gray-500 dark:text-white/40 font-medium">Not enough rated queries yet.</p>}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
