'use client'
import { useEffect, useState } from 'react'
import { TrendingUp, Loader2, BarChart3, Clock, Activity, Zap } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { feedbackApi } from '@/lib/api'

interface MetricCardProps {
  label: string
  value: string | number | null
  unit?: string
  icon: React.ComponentType<{ className?: string }>
  color: string
  description?: string
}

function MetricCard({ label, value, unit, icon: Icon, color, description }: MetricCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5"
    >
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-white/40">{label}</p>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <p className="text-2xl font-bold text-white">
        {value === null || value === undefined ? '—' : value}
        {unit && <span className="text-sm text-white/40 font-normal ml-1">{unit}</span>}
      </p>
      {description && <p className="text-[11px] text-white/30 mt-1.5">{description}</p>}
    </motion.div>
  )
}

// Simple bar chart component
function SimpleBarChart({ data, label }: { data: Record<string, number>; label: string }) {
  const entries = Object.entries(data)
  const max = Math.max(...entries.map(([, v]) => v), 1)
  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5">
      <p className="text-xs font-semibold text-white/60 mb-4">{label}</p>
      <div className="space-y-2.5">
        {entries.map(([key, val]) => (
          <div key={key} className="flex items-center gap-3">
            <span className="text-[11px] text-white/40 w-24 truncate">{key}</span>
            <div className="flex-1 h-5 bg-white/[0.04] rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(val / max) * 100}%` }}
                transition={{ duration: 0.6, delay: 0.1 }}
                className="h-full bg-gradient-to-r from-blue-500 to-violet-500 rounded-full"
              />
            </div>
            <span className="text-[11px] text-white/50 w-10 text-right font-mono">{val}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function QueryAnalyticsPage() {
  const [metrics, setMetrics] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [windowDays, setWindowDays] = useState(30)

  useEffect(() => {
    setLoading(true)
    feedbackApi.getExtendedMetrics(windowDays)
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setLoading(false))
  }, [windowDays])

  const fmt = (n: number | null | undefined, decimals = 1) =>
    n === null || n === undefined ? null : (n * 100).toFixed(decimals) + '%'

  return (
    <PermissionGate permission={Permission.ANALYTICS_VIEW_PLATFORM}>
      <AdminSectionShell
        title="Query Analytics"
        description="Volume, latency, confidence, and retrieval performance over time."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Query Analytics' }]}
        action={
          <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1">
            {[7, 30, 90].map(d => (
              <button key={d} onClick={() => setWindowDays(d)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${windowDays === d ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                {d}d
              </button>
            ))}
          </div>
        }
      >
        {loading ? (
          <div className="flex items-center justify-center py-20 gap-2 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Loading analytics…</span>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Key metrics */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricCard label="Total Queries" value={metrics?.total_queries ?? '—'} icon={BarChart3}
                color="bg-blue-500/15 text-blue-400" description={`Last ${window} days`} />
              <MetricCard label="User Satisfaction" value={fmt(metrics?.user_satisfaction)} icon={TrendingUp}
                color="bg-emerald-500/15 text-emerald-400" description="👍 feedback rate" />
              <MetricCard label="Avg Latency" value={metrics?.avg_latency_ms ? Math.round(metrics.avg_latency_ms) : null}
                unit="ms" icon={Clock} color="bg-amber-500/15 text-amber-400" description="Mean response time" />
              <MetricCard label="Hallucination Rate" value={fmt(metrics?.hallucination_rate)} icon={Activity}
                color="bg-red-500/15 text-red-400" description="Detected hallucinations" />
            </div>

            {/* Phase 15 metrics */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricCard label="Ticket Rate" value={fmt(metrics?.ticket_generation_rate)} icon={Zap}
                color="bg-rose-500/15 text-rose-400" description="Queries → tickets" />
              <MetricCard label="Resolution Rate" value={fmt(metrics?.ticket_resolution_rate)} icon={Activity}
                color="bg-teal-500/15 text-teal-400" description="Tickets resolved" />
              <MetricCard label="Routing Accuracy" value={fmt(metrics?.domain_routing_accuracy)} icon={TrendingUp}
                color="bg-cyan-500/15 text-cyan-400" description="Correct domain routing" />
              <MetricCard label="Avg Resolution" value={metrics?.avg_ticket_resolution_time_hours ? metrics.avg_ticket_resolution_time_hours.toFixed(1) : null}
                unit="hrs" icon={Clock} color="bg-violet-500/15 text-violet-400" description="Ticket resolution time" />
            </div>

            {/* Retrieval by route */}
            {metrics?.retrieval_accuracy_by_route && Object.keys(metrics.retrieval_accuracy_by_route).length > 0 && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <SimpleBarChart data={metrics.retrieval_accuracy_by_route} label="Retrieval Accuracy by Route" />
                {metrics?.signal_counts && Object.keys(metrics.signal_counts).length > 0 && (
                  <SimpleBarChart data={metrics.signal_counts} label="Learning Signal Distribution" />
                )}
              </div>
            )}

            {!metrics && (
              <div className="text-center py-10 text-white/30 text-sm">
                Could not load analytics. Ensure the backend is running and connected.
              </div>
            )}
          </div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
