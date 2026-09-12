'use client'
import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { LineChart, TrendingUp, Clock, Gauge, Activity, AlertCircle, Ticket, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { feedbackApi } from '@/lib/api'

type Tab = 'retrieval' | 'confidence' | 'hallucination' | 'tickets' | 'latency' | 'satisfaction'

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'retrieval',    label: 'Retrieval Accuracy', icon: Gauge },
  { id: 'confidence',   label: 'Confidence',          icon: TrendingUp },
  { id: 'hallucination',label: 'Hallucination Rate',  icon: AlertCircle },
  { id: 'tickets',      label: 'Ticket Stats',        icon: Ticket },
  { id: 'latency',      label: 'Latency',             icon: Clock },
  { id: 'satisfaction', label: 'User Satisfaction',   icon: Activity },
]

function StatCard({ label, value, delta, color, sublabel }: { label: string; value: string | null; delta?: string; color: string; sublabel?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      className={`rounded-xl p-5 border bg-white dark:bg-white/[0.02] shadow-sm ${color}`}
    >
      <p className="text-xs font-medium text-gray-500 dark:text-white/50 mb-1">{label}</p>
      <p className="text-3xl font-bold text-gray-900 dark:text-white">{value ?? '—'}</p>
      {sublabel && <p className="text-[11px] text-gray-400 dark:text-white/30 mt-1">{sublabel}</p>}
      {delta && <p className={`text-xs mt-2 ${delta.startsWith('+') ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>{delta} vs last period</p>}
    </motion.div>
  )
}

function CalibrationChart({ buckets }: { buckets: any[] }) {
  if (!buckets?.length) return null
  const max = Math.max(...buckets.map(b => b.total ?? 0), 1)
  return (
    <div className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl p-5 shadow-sm">
      <p className="text-xs font-semibold text-gray-800 dark:text-white/60 mb-4">Confidence Calibration (predicted vs actual correctness)</p>
      <div className="space-y-3">
        {buckets.map((b, i) => {
          const predicted = Math.round((b.bucket_min + 0.1) * 100)
          const actual = Math.round(b.actual_correctness_rate * 100)
          const isWellCalibrated = Math.abs(predicted - actual) < 15
          return (
            <div key={i} className="flex items-center gap-3">
              <span className="text-[11px] text-gray-500 dark:text-white/35 w-20">{Math.round(b.bucket_min * 100)}–{Math.round((b.bucket_min + 0.2) * 100)}%</span>
              <div className="flex-1 flex gap-1 items-center">
                <div className="flex-1 h-4 bg-gray-100 dark:bg-white/[0.04] rounded-full overflow-hidden relative">
                  <div className="h-full bg-blue-500/30 rounded-full absolute" style={{ width: `${predicted}%` }} />
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${actual}%` }}
                    transition={{ duration: 0.5, delay: i * 0.05 }}
                    className={`h-full rounded-full absolute ${isWellCalibrated ? 'bg-emerald-500/70 dark:bg-emerald-400/70' : 'bg-amber-500/70 dark:bg-amber-400/70'}`}
                  />
                </div>
                <span className={`text-[11px] w-10 text-right font-mono ${isWellCalibrated ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>{actual}%</span>
              </div>
              <span className="text-[10px] text-gray-400 dark:text-white/20 w-16 text-right">{b.total ?? 0} samples</span>
            </div>
          )
        })}
      </div>
      <p className="text-[10px] text-gray-400 dark:text-white/20 mt-3">Blue = predicted confidence · Colored = actual correctness · Green = well-calibrated</p>
    </div>
  )
}

export default function AnalyticsDashboardPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('retrieval')
  const [metrics, setMetrics] = useState<any>(null)
  const [calibration, setCalibration] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [windowDays, setWindowDays] = useState(30)

  // Sync tab state with query parameters
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
    } else {
      setTab('retrieval')
    }
  }, [tabParam])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      feedbackApi.getExtendedMetrics?.(windowDays).catch(() => null),
      feedbackApi.getConfidenceCalibration?.(windowDays).catch(() => []),
    ]).then(([m, c]) => {
      setMetrics(m)
      setCalibration(c ?? [])
    }).finally(() => setLoading(false))
  }, [windowDays])

  const pct = (n: number | null | undefined) => n == null ? null : `${(n * 100).toFixed(1)}%`
  const ms = (n: number | null | undefined) => n == null ? null : `${Math.round(n)}ms`
  const hrs = (n: number | null | undefined) => n == null ? null : `${n.toFixed(1)}h`

  const selectTab = (t: Tab) => {
    router.push(`/admin/analytics?tab=${t}`)
  }

  const tabContent: Record<Tab, React.ReactNode> = {
    retrieval: (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <StatCard label="Avg Retrieval Accuracy" value={metrics ? (Object.values(metrics.retrieval_accuracy_by_route ?? {}).length ? pct(Object.values(metrics.retrieval_accuracy_by_route as Record<string,number>).reduce((a, b) => a + b, 0) / Object.values(metrics.retrieval_accuracy_by_route as Record<string,number>).length) : '—') : null}
            color="border-blue-200 dark:border-blue-500/20" sublabel="Average across all retrieval routes" />
          <StatCard label="Domain Routing Accuracy" value={pct(metrics?.domain_routing_accuracy)}
            color="border-cyan-200 dark:border-cyan-500/20" sublabel="Correct domain assignment rate" />
        </div>
        {metrics?.retrieval_accuracy_by_route && (
          <div className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl p-5 shadow-sm">
            <p className="text-xs font-semibold text-gray-800 dark:text-white/60 mb-4">Accuracy by Retrieval Route</p>
            {Object.entries(metrics.retrieval_accuracy_by_route as Record<string,number>).map(([route, acc]) => (
              <div key={route} className="flex items-center gap-3 mb-3">
                <span className="text-xs text-gray-600 dark:text-white/50 w-20">{route}</span>
                <div className="flex-1 h-4 bg-gray-100 dark:bg-white/[0.04] rounded-full overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${(acc as number) * 100}%` }}
                    transition={{ duration: 0.5 }}
                    className="h-full bg-gradient-to-r from-blue-500 to-blue-400 rounded-full" />
                </div>
                <span className="text-xs font-mono text-gray-600 dark:text-white/50 w-12 text-right">{pct(acc as number)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    ),
    confidence: (
      <div className="space-y-4">
        <CalibrationChart buckets={calibration} />
        {calibration.length === 0 && !loading && (
          <div className="text-center py-10 text-gray-400 dark:text-white/30 text-sm">No calibration data available yet. Collect more 👍/👎 feedback to populate this chart.</div>
        )}
      </div>
    ),
    hallucination: (
      <div className="grid grid-cols-2 gap-4">
        <StatCard label="Hallucination Rate" value={pct(metrics?.hallucination_rate)} color="border-red-200 dark:border-red-500/20" sublabel="% queries with detected hallucinations" />
        <StatCard label="Total Queries Checked" value={metrics?.total_queries ?? null} color="border-gray-200 dark:border-white/[0.08]" sublabel={`Last ${windowDays} days`} />
        {metrics?.signal_counts?.hallucination_detected != null && (
          <StatCard label="Signals (Hallucination)" value={String(metrics.signal_counts.hallucination_detected)} color="border-red-200 dark:border-red-500/20" sublabel="Expert-confirmed hallucinations" />
        )}
      </div>
    ),
    tickets: (
      <div className="grid grid-cols-2 gap-4">
        <StatCard label="Ticket Generation Rate" value={pct(metrics?.ticket_generation_rate)} color="border-rose-200 dark:border-rose-500/20" sublabel="% queries that trigger a ticket" />
        <StatCard label="Ticket Resolution Rate" value={pct(metrics?.ticket_resolution_rate)} color="border-emerald-200 dark:border-emerald-500/20" sublabel="% tickets resolved" />
        <StatCard label="Avg Resolution Time" value={hrs(metrics?.avg_ticket_resolution_time_hours)} color="border-amber-200 dark:border-amber-500/20" sublabel="Mean hours from open → resolved" />
        <StatCard label="Total Tickets" value={metrics?.total_tickets ?? null} color="border-gray-200 dark:border-white/[0.08]" sublabel={`Last ${windowDays} days`} />
      </div>
    ),
    latency: (
      <div className="grid grid-cols-2 gap-4">
        <StatCard label="Avg Total Latency" value={ms(metrics?.avg_latency_ms)} color="border-amber-200 dark:border-amber-500/20" sublabel="End-to-end response time" />
        <StatCard label="P95 Latency" value={ms(metrics?.p95_latency_ms)} color="border-orange-200 dark:border-orange-500/20" sublabel="95th percentile latency" />
      </div>
    ),
    satisfaction: (
      <div className="grid grid-cols-2 gap-4">
        <StatCard label="User Satisfaction" value={pct(metrics?.user_satisfaction)} color="border-emerald-200 dark:border-emerald-500/20" sublabel="👍 feedback rate" />
        <StatCard label="Total Rated Queries" value={metrics?.total_rated ?? null} color="border-gray-200 dark:border-white/[0.08]" sublabel="Queries with 👍/👎 feedback" />
        <StatCard label="Corrections Submitted" value={metrics?.signal_counts?.correction ?? null} color="border-blue-200 dark:border-blue-500/20" sublabel="Free-text corrections from users" />
        <StatCard label="Feedback Rate" value={metrics?.total_queries ? pct((metrics.total_rated ?? 0) / metrics.total_queries) : null}
          color="border-violet-200 dark:border-violet-500/20" sublabel="% queries rated by users" />
      </div>
    ),
  }

  return (
    <PermissionGate permission={Permission.ANALYTICS_VIEW_PLATFORM}>
      <AdminSectionShell
        title="Analytics Dashboard"
        description="Platform-wide performance across all 8 Phase 15 metrics."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Analytics' }]}
        action={
          <div className="flex items-center gap-1 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1">
            {[7, 30, 90].map(d => (
              <button key={d} onClick={() => setWindowDays(d)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${windowDays === d ? 'bg-teal-600 text-white' : 'text-gray-500 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'}`}>
                {d}d
              </button>
            ))}
          </div>
        }
      >
        {/* Sub-tabs */}
        <div className="flex flex-wrap gap-1 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 w-fit mb-6">
          {TABS.map(t => {
            const Icon = t.icon
            return (
              <button key={t.id} onClick={() => selectTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-teal-600 text-white' : 'text-gray-500 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'}`}>
                <Icon className="w-3.5 h-3.5" />{t.label}
              </button>
            )
          })}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20 gap-2 text-gray-400 dark:text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading analytics…</span>
          </div>
        ) : (
          <motion.div key={tab} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
            {tabContent[tab]}
          </motion.div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
