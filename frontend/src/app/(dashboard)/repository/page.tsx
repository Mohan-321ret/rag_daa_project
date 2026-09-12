'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Database, Network, Search, Filter, HardDrive, GitBranch } from 'lucide-react'
import { PageHeader, Card, ConfidenceMeter } from '@/components/shared/index'
import { mockDocuments, mockKnowledgeSources, mockKnowledgeNodes } from '@/data/mockData'
import { formatBytes, formatNumber, formatDateTime } from '@/lib/utils'
import { StatusBadge } from '@/components/shared/index'

const storageData = [
  { label: 'Vector Store', used: 42.3, total: 100, color: '#6366f1' },
  { label: 'Graph DB', used: 18.7, total: 50, color: '#3b82f6' },
  { label: 'Metadata', used: 8.2, total: 20, color: '#10b981' },
  { label: 'Versions', used: 31.5, total: 80, color: '#f59e0b' },
]

export default function RepositoryPage() {
  const [activeTab, setActiveTab] = useState<'vectors' | 'graph' | 'sources' | 'versions'>('vectors')
  const [search, setSearch] = useState('')

  const filtered = mockDocuments.filter(d => !search || d.name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Repository" description="Unified view of all knowledge stores, graphs, and metadata" />

      {/* Storage Overview */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {storageData.map((s, i) => (
          <motion.div key={s.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
            className="bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-medium text-gray-600 dark:text-white/60">{s.label}</p>
              <HardDrive className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
            </div>
            <p className="text-xl font-bold text-gray-900 dark:text-white mb-1">{s.used} <span className="text-sm font-normal text-gray-500 dark:text-white/30">/ {s.total} GB</span></p>
            <div className="h-1.5 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden">
              <motion.div initial={{ width: 0 }} animate={{ width: `${(s.used / s.total) * 100}%` }} transition={{ duration: 0.8, delay: i * 0.1 }}
                className="h-full rounded-full" style={{ background: s.color }} />
            </div>
            <p className="text-[10px] text-gray-500 dark:text-white/30 mt-1">{((s.used / s.total) * 100).toFixed(0)}% used</p>
          </motion.div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 w-fit">
        {[
          { id: 'vectors', label: '🧠 Vector Store' },
          { id: 'graph', label: '🕸️ Knowledge Graph' },
          { id: 'sources', label: '📡 Sources' },
          { id: 'versions', label: '📦 Versions' },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`px-4 py-2 rounded-lg text-xs font-medium transition-all ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/70'}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'vectors' && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Vector Database</h3>
              <p className="text-xs text-gray-500 dark:text-white/40 mt-0.5">847,293 vectors · text-embedding-3-large · 1536 dimensions</p>
            </div>
            <div className="flex items-center gap-2 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-1.5">
              <Search className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search documents..." className="bg-transparent text-xs text-gray-800 dark:text-white/60 placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none w-40" />
            </div>
          </div>
          <div className="space-y-2">
            {filtered.slice(0, 8).map((doc, i) => (
              <motion.div key={doc.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}
                className="flex items-center gap-4 p-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04] hover:border-gray-300 dark:hover:border-white/[0.08] transition-all">
                <div className="w-8 h-8 rounded-lg bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center text-sm">📄</div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-900 dark:text-white/80 truncate">{doc.name}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/30">{doc.department} · {doc.language.toUpperCase()}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs font-semibold text-gray-800 dark:text-white/70">{doc.embeddingCount > 0 ? doc.embeddingCount.toLocaleString() : '—'}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/30">vectors</p>
                </div>
                <div className="w-24">
                  {doc.confidenceScore > 0 ? <ConfidenceMeter value={doc.confidenceScore} size="sm" /> : <span className="text-[10px] text-gray-400 dark:text-white/20">Processing...</span>}
                </div>
                <StatusBadge status={doc.status} />
              </motion.div>
            ))}
          </div>
        </Card>
      )}

      {activeTab === 'graph' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Knowledge Graph Nodes</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {mockKnowledgeNodes.map((node, i) => (
              <motion.div key={node.id} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.05 }}
                className="flex items-center gap-3 p-3 rounded-xl bg-gray-50 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.06] hover:border-gray-300 dark:hover:border-white/[0.12] transition-all">
                <div className={`w-3 h-3 rounded-full flex-shrink-0 ${node.type === 'concept' ? 'bg-blue-500' : node.type === 'entity' ? 'bg-violet-500' : node.type === 'document' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                <div className="flex-1">
                  <p className="text-xs font-medium text-gray-900 dark:text-white/80">{node.label}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/30 capitalize">{node.type} · {node.connections} connections</p>
                </div>
                <div className="w-20">
                  <ConfidenceMeter value={node.weight} size="sm" />
                </div>
              </motion.div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-4 text-[11px] text-gray-500 dark:text-white/40">
            {[{ color: 'bg-blue-500', label: 'Concept' }, { color: 'bg-violet-500', label: 'Entity' }, { color: 'bg-emerald-500', label: 'Document' }, { color: 'bg-amber-500', label: 'Relation' }].map(l => (
              <div key={l.label} className="flex items-center gap-1.5"><div className={`w-2 h-2 rounded-full ${l.color}`} />{l.label}</div>
            ))}
          </div>
        </Card>
      )}

      {activeTab === 'sources' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Knowledge Sources</h3>
          <div className="space-y-3">
            {mockKnowledgeSources.map((src, i) => (
              <motion.div key={src.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 p-4 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.05] hover:border-gray-300 dark:hover:border-white/[0.1] transition-all">
                <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-white/[0.05] flex items-center justify-center text-lg">
                  {src.type === 'database' ? '🗄️' : src.type === 'api' ? '🔌' : src.type === 'file_system' ? '📁' : src.type === 'web' ? '🌐' : '📧'}
                </div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-white/80">{src.name}</p>
                  <p className="text-xs text-gray-500 dark:text-white/40">{src.department} · Last sync: {formatDateTime(src.lastSync)}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold text-gray-900 dark:text-white">{formatNumber(src.documentCount)}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/30">documents</p>
                </div>
                <StatusBadge status={src.status} size="md" />
              </motion.div>
            ))}
          </div>
        </Card>
      )}

      {activeTab === 'versions' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Version Repository</h3>
          <div className="space-y-2">
            {[
              { v: 8, docs: 4821, size: '12.4 GB', date: '2024-12-15', status: 'current' },
              { v: 7, docs: 4774, size: '12.1 GB', date: '2024-12-14', status: 'stable' },
              { v: 6, docs: 4720, size: '11.9 GB', date: '2024-12-13', status: 'stable' },
              { v: 5, docs: 4650, size: '11.6 GB', date: '2024-12-12', status: 'stable' },
              { v: 4, docs: 4580, size: '11.3 GB', date: '2024-12-10', status: 'deprecated' },
            ].map((v, i) => (
              <motion.div key={v.v} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 p-3 rounded-xl bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.04]">
                <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-white/[0.05] flex items-center justify-center">
                  <GitBranch className="w-4 h-4 text-gray-500 dark:text-white/40" />
                </div>
                <div className="flex-1">
                  <p className="text-xs font-bold text-gray-900 dark:text-white">Version {v.v}</p>
                  <p className="text-[10px] text-gray-500 dark:text-white/40">{v.date} · {v.docs.toLocaleString()} documents</p>
                </div>
                <p className="text-xs text-gray-600 dark:text-white/50">{v.size}</p>
                <StatusBadge status={v.status} />
              </motion.div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
