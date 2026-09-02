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
        <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1">
          {windows.map(w => (
            <button key={w} onClick={() => setWindowDays(w)}
              className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all ${windowDays === w ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
              {w}d
            </button>
          ))}
        </div>
      </PageHeader>

      {isError && <Card><p className="text-sm text-red-400 text-center py-4">{error instanceof ApiError ? error.message : 'Failed to load metrics'}</p></Card>}

      {!isError && !isLoading && data && data.total_queries === 0 && (
        <Card><EmptyState icon={<TrendingUp className="w-5 h-5" />} title="No queries logged yet" description="Ask questions on the Enterprise LLM page and rate the answers to populate these metrics." /></Card>
      )}

      {data && data.total_queries > 0 && (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'User Satisfaction', value: data.user_satisfaction != null ? `${(data.user_satisfaction * 100).toFixed(0)}%` : '—', icon: <ThumbsUp className="w-4 h-4" />, color: 'text-amber-400', bg: 'bg-amber-500/10' },
              { label: 'Total Queries', value: data.total_queries, icon: <MessageSquare className="w-4 h-4" />, color: 'text-blue-400', bg: 'bg-blue-500/10' },
              { label: 'Rated Queries', value: data.total_rated, icon: <Target className="w-4 h-4" />, color: 'text-violet-400', bg: 'bg-violet-500/10' },
              { label: 'Hallucination Rate', value: data.hallucination_rate != null ? `${(data.hallucination_rate * 100).toFixed(1)}%` : '—', icon: <AlertTriangle className="w-4 h-4" />, color: 'text-red-400', bg: 'bg-red-500/10' },
            ].map((s, i) => (
              <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                className={`${s.bg} rounded-2xl p-4 flex items-center gap-3`}>
                <div className={s.color}>{s.icon}</div>
                <div>
                  <p className="text-xl font-bold text-white">{s.value}</p>
                  <p className="text-[11px] text-white/40">{s.label}</p>
                </div>
              </motion.div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Latency */}
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-white/70">Latency</h3>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-white/[0.03] rounded-xl p-4 text-center">
                  <p className="text-2xl font-bold text-white">{data.avg_latency_ms ? Math.round(data.avg_latency_ms) : '—'}ms</p>
                  <p className="text-[11px] text-white/40 mt-1">Average</p>
                </div>
                <div className="bg-white/[0.03] rounded-xl p-4 text-center">
                  <p className="text-2xl font-bold text-white">{data.p95_latency_ms ? Math.round(data.p95_latency_ms) : '—'}ms</p>
                  <p className="text-[11px] text-white/40 mt-1">P95</p>
                </div>
              </div>
            </Card>

            {/* Queries by route */}
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-white/70">Queries by Retrieval Route</h3>
              </div>
              {routeData.length === 0 ? <p className="text-xs text-white/30">No route data yet</p> : (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={routeData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="route" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: '#12121f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12 }} />
                    <Bar dataKey="count" name="Queries" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          {/* Retrieval accuracy by route */}
          <Card>
            <div className="flex items-center gap-2 mb-4">
              <Target className="w-4 h-4 text-violet-400" />
              <h3 className="text-sm font-semibold text-white/70">Retrieval Accuracy by Route (👍 share of rated queries)</h3>
            </div>
            <div className="space-y-3">
              {routeData.map(r => (
                <div key={r.route}>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-white/60 uppercase">{r.route}</span>
                    <span className="text-white/40">{r.accuracy != null ? `${(r.accuracy * 100).toFixed(0)}%` : '—'} · {r.samples} samples</span>
                  </div>
                  <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${(r.accuracy ?? 0) * 100}%` }} transition={{ duration: 0.8 }}
                      className="h-full rounded-full bg-gradient-to-r from-violet-500 to-blue-500" />
                  </div>
                </div>
              ))}
              {routeData.length === 0 && <p className="text-xs text-white/30">Not enough rated queries yet.</p>}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
