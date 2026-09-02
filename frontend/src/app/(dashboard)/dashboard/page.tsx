'use client'
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  FileText, Cpu, GitBranch, Search, Clock, ShieldCheck, AlertTriangle, Activity,
  CheckCircle, XCircle, Loader2, Eye,
} from 'lucide-react'
import {
  AreaChart, Area, PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { StatCard } from '@/components/shared/StatCard'
import { Card, SectionTitle, EmptyState } from '@/components/shared/index'
import { formatNumber, formatRelativeTime } from '@/lib/utils'
import {
  documentsApi, ragApi, feedbackApi, evolutionApi, healthApi, llmApi,
} from '@/lib/api'

const ROUTE_COLORS: Record<string, string> = { vector: '#3b82f6', bm25: '#10b981', graph: '#8b5cf6', hybrid: '#06b6d4' }
const STATUS_COLORS: Record<string, string> = { indexed: '#10b981', processing: '#3b82f6', failed: '#ef4444' }

const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number; name: string; color: string }>; label?: string }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-[#12121f] border border-white/10 rounded-xl p-3 shadow-2xl">
      <p className="text-xs text-white/50 mb-2">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="text-xs font-medium" style={{ color: p.color }}>{p.name}: {p.value.toLocaleString()}</p>
      ))}
    </div>
  )
}

export default function DashboardPage() {
  const { data: docsData, isLoading: docsLoading } = useQuery({
    queryKey: ['dashboard-documents'],
    queryFn: () => documentsApi.list(0, 500),
  })
  const { data: ragStatus } = useQuery({ queryKey: ['dashboard-rag-status'], queryFn: () => ragApi.status() })
  const { data: metrics } = useQuery({ queryKey: ['dashboard-feedback-metrics'], queryFn: () => feedbackApi.metrics(30) })
  const { data: changes } = useQuery({ queryKey: ['dashboard-evolution-changes'], queryFn: () => evolutionApi.changes({ limit: 8 }) })
  const { data: watcher } = useQuery({ queryKey: ['dashboard-watcher'], queryFn: () => evolutionApi.watcherStatus() })
  const { data: health } = useQuery({ queryKey: ['dashboard-health'], queryFn: () => healthApi.check() })
  const { data: models } = useQuery({ queryKey: ['dashboard-llm-models'], queryFn: () => llmApi.models() })

  const docs = docsData?.documents ?? []

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { indexed: 0, processing: 0, failed: 0 }
    docs.forEach(d => { counts[d.processing_status] = (counts[d.processing_status] ?? 0) + 1 })
    return counts
  }, [docs])

  const departmentData = useMemo(() => {
    const counts: Record<string, number> = {}
    docs.forEach(d => { const dep = d.department || 'Unassigned'; counts[dep] = (counts[dep] ?? 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, value]) => ({ name, value }))
  }, [docs])

  const ingestByDay = useMemo(() => {
    const days: { date: string; label: string; count: number }[] = []
    for (let i = 13; i >= 0; i--) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      const date = d.toISOString().slice(0, 10)
      days.push({ date, label: `${d.getMonth() + 1}/${d.getDate()}`, count: 0 })
    }
    docs.forEach(d => {
      const date = d.upload_date.slice(0, 10)
      const bucket = days.find(x => x.date === date)
      if (bucket) bucket.count += 1
    })
    return days
  }, [docs])

  const routeData = metrics
    ? Object.entries(metrics.queries_by_route).map(([name, value]) => ({ name, value, color: ROUTE_COLORS[name] ?? '#6b7280' }))
    : []

  const statusPieData = [
    { name: 'Completed', value: statusCounts.indexed ?? 0, color: STATUS_COLORS.indexed },
    { name: 'Processing', value: statusCounts.processing ?? 0, color: STATUS_COLORS.processing },
    { name: 'Failed', value: statusCounts.failed ?? 0, color: STATUS_COLORS.failed },
  ].filter(d => d.value > 0)

  const llmReachable = (models?.installed_raw.length ?? 0) > 0
  const servicesHealthy = [
    health?.services.postgres === 'ok',
    health?.services.neo4j === 'ok',
    llmReachable,
    watcher?.running,
  ]
  const healthPct = servicesHealthy.length ? Math.round((servicesHealthy.filter(Boolean).length / servicesHealthy.length) * 100) : null

  const changeIcon = (type: string) => type === 'new_document' ? <FileText className="w-3.5 h-3.5 text-blue-400" /> : type === 'new_version' ? <GitBranch className="w-3.5 h-3.5 text-amber-400" /> : <CheckCircle className="w-3.5 h-3.5 text-white/30" />

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="text-2xl font-bold text-white">
          Enterprise Overview
        </motion.h1>
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }} className="text-sm text-white/40 mt-1">
          Live status across your ingested knowledge base and RAG pipeline
        </motion.p>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        <StatCard title="Total Documents" value={formatNumber(docsData?.total ?? 0)} icon={<FileText className="w-4 h-4" />} delay={0} />
        <StatCard title="Indexed Chunks" value={formatNumber(ragStatus?.total_indexed_chunks ?? 0)} icon={<Cpu className="w-4 h-4" />} delay={0.05} />
        <StatCard title="Failed Documents" value={statusCounts.failed ?? 0} icon={<AlertTriangle className="w-4 h-4" />} delay={0.1} />
        <StatCard title="Processing Now" value={statusCounts.processing ?? 0} icon={<Loader2 className="w-4 h-4" />} delay={0.15} />
        <StatCard title="Queries (30d)" value={formatNumber(metrics?.total_queries ?? 0)} icon={<Search className="w-4 h-4" />} delay={0.2} />
        <StatCard title="User Satisfaction" value={metrics?.user_satisfaction != null ? `${(metrics.user_satisfaction * 100).toFixed(0)}%` : '—'} icon={<ShieldCheck className="w-4 h-4" />} delay={0.25} />
        <StatCard title="Hallucination Rate" value={metrics?.hallucination_rate != null ? `${(metrics.hallucination_rate * 100).toFixed(1)}%` : '—'} icon={<AlertTriangle className="w-4 h-4" />} delay={0.3} />
        <StatCard title="Avg Latency" value={metrics?.avg_latency_ms ? Math.round(metrics.avg_latency_ms) : '—'} suffix="ms" icon={<Clock className="w-4 h-4" />} delay={0.35} />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Ingestion volume */}
        <Card className="lg:col-span-2">
          <SectionTitle>Documents Ingested — Last 14 Days</SectionTitle>
          {docsLoading ? <div className="h-[220px] animate-pulse bg-white/[0.03] rounded-xl" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={ingestByDay}>
                <defs>
                  <linearGradient id="qGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="label" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="count" name="Documents" stroke="#6366f1" fill="url(#qGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Retrieval Methods */}
        <Card>
          <SectionTitle>Queries by Retrieval Route (30d)</SectionTitle>
          {routeData.length === 0 ? (
            <EmptyState icon={<Search className="w-5 h-5" />} title="No queries yet" description="Ask something on the Enterprise LLM page." />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie data={routeData} cx="50%" cy="50%" innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                    {routeData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="grid grid-cols-2 gap-2 mt-2">
                {routeData.map(d => (
                  <div key={d.name} className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.color }} />
                    <span className="text-[11px] text-white/50 uppercase">{d.name}</span>
                    <span className="text-[11px] text-white/70 ml-auto font-medium">{d.value}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Document status */}
        <Card>
          <SectionTitle>Documents by Status</SectionTitle>
          {statusPieData.length === 0 ? (
            <EmptyState icon={<FileText className="w-5 h-5" />} title="No documents yet" />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={statusPieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                  {statusPieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Dept Distribution */}
        <Card>
          <SectionTitle>Documents by Department</SectionTitle>
          {departmentData.length === 0 ? <EmptyState icon={<FileText className="w-5 h-5" />} title="No documents yet" /> : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={departmentData} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={90} tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" name="Documents" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Service Health */}
        <Card>
          <SectionTitle>Service Health</SectionTitle>
          <div className="space-y-2.5">
            {[
              { label: 'PostgreSQL', ok: health?.services.postgres === 'ok' },
              { label: 'Neo4j', ok: health?.services.neo4j === 'ok' },
              { label: `LLM (${models?.provider ?? '—'})`, ok: llmReachable },
              { label: 'Folder Watcher', ok: watcher?.running },
            ].map(s => (
              <div key={s.label} className="flex items-center justify-between py-1.5 border-b border-white/[0.04]">
                <span className="text-xs text-white/60">{s.label}</span>
                {s.ok ? <CheckCircle className="w-4 h-4 text-emerald-400" /> : <XCircle className="w-4 h-4 text-red-400" />}
              </div>
            ))}
            {healthPct !== null && (
              <div className="pt-1">
                <div className="flex justify-between text-[11px] mb-1"><span className="text-white/40">Overall</span><span className="text-white/70 font-medium">{healthPct}%</span></div>
                <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${healthPct}%` }} className={`h-full rounded-full ${healthPct >= 75 ? 'bg-emerald-500' : healthPct >= 50 ? 'bg-amber-500' : 'bg-red-500'}`} />
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <SectionTitle>Recent Knowledge Evolution Activity</SectionTitle>
          {(changes?.events.length ?? 0) === 0 ? (
            <EmptyState icon={<Activity className="w-5 h-5" />} title="No activity yet" description="Upload a document to see it appear here." />
          ) : (
            <div className="space-y-2">
              {changes!.events.map((e, i) => (
                <motion.div key={e.event_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
                  className="flex items-center gap-3 p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                  {changeIcon(e.change_type)}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-white/70 truncate">{e.filename}</p>
                    <p className="text-[10px] text-white/30 capitalize">{e.change_type.replace(/_/g, ' ')}</p>
                  </div>
                  <span className="text-[10px] text-white/25 flex-shrink-0">{formatRelativeTime(e.detected_at)}</span>
                </motion.div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle>Currently Processing / Recently Indexed</SectionTitle>
          {docs.length === 0 ? (
            <EmptyState icon={<Eye className="w-5 h-5" />} title="No documents yet" />
          ) : (
            <div className="space-y-2">
              {docs.slice(0, 6).map((d, i) => (
                <motion.div key={d.document_id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }}
                  className="flex items-center justify-between p-3 rounded-xl bg-white/[0.03] border border-white/[0.05]">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-white/80 truncate max-w-[220px]">{d.original_filename}</p>
                    <p className="text-[10px] text-white/30 mt-0.5">{d.department ?? 'Unassigned'} · {formatRelativeTime(d.upload_date)}</p>
                  </div>
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${d.processing_status === 'indexed' ? 'bg-emerald-500/15 text-emerald-400' : d.processing_status === 'failed' ? 'bg-red-500/15 text-red-400' : 'bg-blue-500/15 text-blue-400'}`}>
                    {d.processing_status}
                  </span>
                </motion.div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
