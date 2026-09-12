'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Lock, Users, Shield, FileText, Eye, Key, AlertTriangle } from 'lucide-react'
import { PageHeader, Card, StatusBadge } from '@/components/shared/index'
import { mockAuditLogs, mockUsers } from '@/data/mockData'
import { formatDateTime } from '@/lib/utils'

const permissions = [
  { role: 'Admin', read: true, write: true, delete: true, manage: true, audit: true },
  { role: 'Engineer', read: true, write: true, delete: false, manage: false, audit: false },
  { role: 'Analyst', read: true, write: false, delete: false, manage: false, audit: false },
  { role: 'Viewer', read: true, write: false, delete: false, manage: false, audit: false },
]

export default function SecurityPage() {
  const [activeTab, setActiveTab] = useState<'overview' | 'rbac' | 'audit' | 'sessions'>('overview')

  return (
    <div className="space-y-6">
      <PageHeader title="Security & Governance" description="Authentication, access control, audit logs, and compliance management" />

      {/* Security Score */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Security Score', value: '98/100', icon: <Shield className="w-4 h-4" />, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-transparent' },
          { label: 'Active Sessions', value: '47', icon: <Users className="w-4 h-4" />, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-transparent' },
          { label: 'Failed Logins', value: '3', icon: <AlertTriangle className="w-4 h-4" />, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-transparent' },
          { label: 'Encryption', value: 'AES-256', icon: <Lock className="w-4 h-4" />, color: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-50 dark:bg-violet-500/10 border border-violet-200 dark:border-transparent' },
        ].map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className={`${s.bg} rounded-2xl p-4 flex items-center gap-3`}>
            <div className={s.color}>{s.icon}</div>
            <div>
              <p className="text-xl font-bold text-gray-900 dark:text-white">{s.value}</p>
              <p className="text-[11px] text-gray-500 dark:text-white/40 font-medium">{s.label}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 w-fit">
        {[
          { id: 'overview', label: '🛡️ Overview' },
          { id: 'rbac', label: '👥 RBAC' },
          { id: 'audit', label: '📋 Audit Logs' },
          { id: 'sessions', label: '🔐 Sessions' },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`px-4 py-2 rounded-lg text-xs font-medium transition-all ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/70'}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70 mb-4">Security Controls</h3>
            <div className="space-y-3">
              {[
                { label: 'Multi-Factor Authentication', status: 'active', detail: 'TOTP + Hardware Keys' },
                { label: 'End-to-End Encryption', status: 'active', detail: 'AES-256-GCM' },
                { label: 'Zero-Trust Network', status: 'active', detail: 'mTLS + SPIFFE' },
                { label: 'Data Loss Prevention', status: 'active', detail: 'Real-time scanning' },
                { label: 'Vulnerability Scanning', status: 'active', detail: 'Daily automated scans' },
                { label: 'SOC 2 Type II', status: 'active', detail: 'Certified 2024' },
              ].map(item => (
                <div key={item.label} className="flex items-center justify-between p-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04]">
                  <div>
                    <p className="text-xs font-medium text-gray-900 dark:text-white/80">{item.label}</p>
                    <p className="text-[10px] text-gray-500 dark:text-white/40">{item.detail}</p>
                  </div>
                  <StatusBadge status={item.status} />
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70 mb-4">Compliance Status</h3>
            <div className="space-y-3">
              {[
                { standard: 'GDPR', status: 'Compliant', score: 98 },
                { standard: 'HIPAA', status: 'Compliant', score: 96 },
                { standard: 'SOC 2', status: 'Certified', score: 100 },
                { standard: 'ISO 27001', status: 'Compliant', score: 94 },
                { standard: 'CCPA', status: 'Compliant', score: 97 },
              ].map(c => (
                <div key={c.standard} className="flex items-center gap-3">
                  <span className="text-xs font-mono font-bold text-gray-700 dark:text-white/60 w-20">{c.standard}</span>
                  <div className="flex-1 h-1.5 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${c.score}%` }} transition={{ duration: 0.8 }}
                      className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400" />
                  </div>
                  <span className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold w-8">{c.score}%</span>
                  <StatusBadge status="active" />
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'rbac' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70 mb-4">Permissions Matrix</h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-white/[0.06]">
                  <th className="text-left py-3 px-4 text-[11px] font-semibold text-gray-500 dark:text-white/40 uppercase tracking-wider">Role</th>
                  {['Read', 'Write', 'Delete', 'Manage', 'Audit'].map(p => (
                    <th key={p} className="text-center py-3 px-4 text-[11px] font-semibold text-gray-500 dark:text-white/40 uppercase tracking-wider">{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {permissions.map((row, i) => (
                  <motion.tr key={row.role} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }}
                    className="border-b border-gray-200 dark:border-white/[0.04]">
                    <td className="py-3 px-4">
                      <span className="text-xs font-semibold text-gray-900 dark:text-white/80">{row.role}</span>
                    </td>
                    {[row.read, row.write, row.delete, row.manage, row.audit].map((allowed, j) => (
                      <td key={j} className="py-3 px-4 text-center">
                        {allowed ? <span className="text-emerald-600 dark:text-emerald-400 text-base font-bold">✓</span> : <span className="text-gray-300 dark:text-white/20 text-base">—</span>}
                      </td>
                    ))}
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {activeTab === 'audit' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70 mb-4">Audit Logs</h3>
          <div className="space-y-2">
            {mockAuditLogs.map((log, i) => (
              <motion.div key={log.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}
                className="flex items-center gap-4 p-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04] hover:border-gray-300 dark:hover:border-white/[0.08] transition-all">
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${log.status === 'success' ? 'bg-emerald-500' : log.status === 'failed' ? 'bg-red-500' : 'bg-amber-500'}`} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-semibold text-gray-800 dark:text-white/70">{log.action}</span>
                    <span className="text-[10px] text-gray-400 dark:text-white/30">·</span>
                    <span className="text-[11px] text-gray-600 dark:text-white/50">{log.resource}</span>
                  </div>
                  <p className="text-[10px] text-gray-500 dark:text-white/30 mt-0.5">User: {log.userId} · IP: {log.ip}</p>
                </div>
                <div className="text-right">
                  <StatusBadge status={log.status} />
                  <p className="text-[10px] text-gray-400 dark:text-white/25 mt-1">{formatDateTime(log.timestamp)}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </Card>
      )}

      {activeTab === 'sessions' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-800 dark:text-white/70 mb-4">Active Sessions</h3>
          <div className="space-y-3">
            {mockUsers.map((user, i) => (
              <motion.div key={user.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 p-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.05]">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-sm">
                  {user.name.split(' ').map(n => n[0]).join('')}
                </div>
                <div className="flex-1">
                  <p className="text-xs font-medium text-gray-900 dark:text-white/80">{user.name}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/40">{user.email} · {user.department}</p>
                </div>
                <span className="text-[10px] bg-gray-100 dark:bg-white/[0.06] text-gray-600 dark:text-white/50 px-2 py-0.5 rounded-full capitalize font-medium">{user.role}</span>
                <StatusBadge status="active" />
                <button className="text-[11px] text-red-600 dark:text-red-400/60 hover:text-red-700 dark:hover:text-red-400 transition-colors font-medium">Revoke</button>
              </motion.div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
