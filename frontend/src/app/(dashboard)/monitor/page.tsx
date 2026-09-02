'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, Cpu, HardDrive, MemoryStick, AlertTriangle, CheckCircle, XCircle, RefreshCw } from 'lucide-react'
import { PageHeader, Card, StatusBadge } from '@/components/shared/index'
import { mockSystemMetrics } from '@/data/mockData'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

const services = [
  { name: 'Vector Database', status: 'active', latency: '2ms', uptime: '99.99%' },
  { name: 'Embedding Service', status: 'active', latency: '45ms', uptime: '99.95%' },
  { name: 'LLM Gateway', status: 'active', latency: '120ms', uptime: '99.87%' },
  { name: 'Knowledge Graph', status: 'active', latency: '8ms', uptime: '99.98%' },
  { name: 'OCR Service', status: 'processing', latency: '340ms', uptime: '99.72%' },
  { name: 'Auth Service', status: 'active', latency: '5ms', uptime: '100%' },
  { name: 'Search Index', status: 'active', latency: '12ms', uptime: '99.96%' },
  { name: 'File Storage', status: 'active', latency: '18ms', uptime: '99.99%' },
]

const recentErrors = [
  { id: 'e1', service: 'OCR Service', message: 'Timeout processing large PDF (>50MB)', severity: 'warning', time: '2 min ago' },
  { id: 'e2', service: 'LLM Gateway', message: 'Rate limit exceeded for GPT-4o endpoint', severity: 'warning', time: '15 min ago' },
  { id: 'e3', service: 'Embedding Service', message: 'Batch processing queue depth: 47 items', severity: 'info', time: '32 min ago' },
]

export default function MonitorPage() {
  const [refreshing, setRefreshing] = useState(false)
  const latest = mockSystemMetrics[mockSystemMetrics.length - 1]

  const handleRefresh = async () => {
    setRefreshing(true)
    await new Promise(r => setTimeout(r, 1000))
    setRefreshing(false)
  }

  const chartData = mockSystemMetrics.slice(-12).map((m, i) => ({
    time: `${i * 2}h`,
    cpu: Math.round(m.cpu),
    memory: Math.round(m.memory),
    storage: Math.round(m.storage),
  }))

  return (
    <div className="space-y-6">
      <PageHeader title="System Monitor" description="Real-time infrastructure health and performance metrics">
        <button onClick={handleRefresh} className={`flex items-center gap-2 px-4 py-2 rounded-xl border border-white/[0.08] text-xs text-white/60 hover:text-white/80 transition-all ${refreshing ? 'opacity-60' : ''}`}>
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </PageHeader>

      {/* System Health Banner */}
      <div className="p-4 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-3">
        <CheckCircle className="w-5 h-5 text-emerald-400" />
        <div>
          <p className="text-sm font-semibold text-white">All Systems Operational</p>
          <p className="text-xs text-white/50">8/8 services running · Last checked: just now</p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-2xl font-bold text-emerald-400">98.7%</p>
          <p className="text-xs text-white/40">Overall Uptime</p>
        </div>
      </div>

      {/* Resource Gauges */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'CPU Usage', value: Math.round(latest.cpu), unit: '%', icon: <Cpu className="w-4 h-4" />, color: latest.cpu > 80 ? 'text-red-400' : latest.cpu > 60 ? 'text-amber-400' : 'text-emerald-400', bar: latest.cpu > 80 ? 'bg-red-500' : latest.cpu > 60 ? 'bg-amber-500' : 'bg-emerald-500' },
          { label: 'Memory', value: Math.round(latest.memory), unit: '%', icon: <MemoryStick className="w-4 h-4" />, color: latest.memory > 80 ? 'text-red-400' : latest.memory > 60 ? 'text-amber-400' : 'text-blue-400', bar: latest.memory > 80 ? 'bg-red-500' : latest.memory > 60 ? 'bg-amber-500' : 'bg-blue-500' },
          { label: 'Storage', value: Math.round(latest.storage), unit: '%', icon: <HardDrive className="w-4 h-4" />, color: 'text-violet-400', bar: 'bg-violet-500' },
          { label: 'Embed Queue', value: latest.embeddingQueue, unit: ' jobs', icon: <Activity className="w-4 h-4" />, color: 'text-cyan-400', bar: 'bg-cyan-500' },
        ].map((m, i) => (
          <motion.div key={m.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className={`${m.color} opacity-70`}>{m.icon}</div>
              <span className={`text-2xl font-bold ${m.color}`}>{m.value}<span className="text-sm font-normal text-white/30">{m.unit}</span></span>
            </div>
            <p className="text-[11px] text-white/40 mb-2">{m.label}</p>
            <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
              <motion.div initial={{ width: 0 }} animate={{ width: `${Math.min(typeof m.value === 'number' ? m.value : 50, 100)}%` }} transition={{ duration: 0.8, delay: i * 0.1 }}
                className={`h-full rounded-full ${m.bar}`} />
            </div>
          </motion.div>
        ))}
      </div>

      {/* Charts */}
      <Card>
        <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-4">Resource Usage — Last 24 Hours</h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData}>
            <defs>
              {[{ id: 'cpu', color: '#3b82f6' }, { id: 'mem', color: '#8b5cf6' }, { id: 'stor', color: '#10b981' }].map(g => (
                <linearGradient key={g.id} id={g.id} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={g.color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={g.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, 100]} tickFormatter={v => `${v}%`} />
            <Tooltip contentStyle={{ background: '#12121f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12 }} />
            <Area type="monotone" dataKey="cpu" name="CPU" stroke="#3b82f6" fill="url(#cpu)" strokeWidth={2} dot={false} />
            <Area type="monotone" dataKey="memory" name="Memory" stroke="#8b5cf6" fill="url(#mem)" strokeWidth={2} dot={false} />
            <Area type="monotone" dataKey="storage" name="Storage" stroke="#10b981" fill="url(#stor)" strokeWidth={2} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Services */}
        <Card>
          <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-4">Service Status</h3>
          <div className="space-y-2">
            {services.map((svc, i) => (
              <motion.div key={svc.name} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}
                className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-white/[0.02] transition-colors">
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${svc.status === 'active' ? 'bg-emerald-400' : 'bg-blue-400 animate-pulse'}`} />
                <span className="text-xs text-white/70 flex-1">{svc.name}</span>
                <span className="text-[11px] text-white/40 font-mono">{svc.latency}</span>
                <span className="text-[11px] text-white/40">{svc.uptime}</span>
                <StatusBadge status={svc.status} />
              </motion.div>
            ))}
          </div>
        </Card>

        {/* Errors */}
        <Card>
          <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-4">Recent Alerts</h3>
          <div className="space-y-3">
            {recentErrors.map((err, i) => (
              <motion.div key={err.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                className={`p-3 rounded-xl border ${err.severity === 'warning' ? 'border-amber-500/20 bg-amber-500/5' : 'border-blue-500/20 bg-blue-500/5'}`}>
                <div className="flex items-center gap-2 mb-1">
                  {err.severity === 'warning' ? <AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> : <Activity className="w-3.5 h-3.5 text-blue-400" />}
                  <span className="text-xs font-semibold text-white/70">{err.service}</span>
                  <span className="text-[10px] text-white/30 ml-auto">{err.time}</span>
                </div>
                <p className="text-[11px] text-white/50">{err.message}</p>
              </motion.div>
            ))}
            <div className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 flex items-center gap-2">
              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              <p className="text-[11px] text-emerald-400/70">No critical errors in the last 24 hours</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
