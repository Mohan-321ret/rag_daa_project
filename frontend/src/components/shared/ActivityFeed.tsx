'use client'
import { motion } from 'framer-motion'
import { formatRelativeTime } from '@/lib/utils'
import { cn } from '@/lib/utils'

interface ActivityItem {
  id: string; title: string; description: string; timestamp: string
  type: 'upload' | 'query' | 'update' | 'alert' | 'system'; status?: 'success' | 'warning' | 'error'
}

const typeColors: Record<string, string> = {
  upload: 'bg-blue-500', query: 'bg-violet-500', update: 'bg-emerald-500', alert: 'bg-amber-500', system: 'bg-cyan-500',
}
const typeBg: Record<string, string> = {
  upload: 'bg-blue-50 dark:bg-blue-500/10', query: 'bg-violet-50 dark:bg-violet-500/10',
  update: 'bg-emerald-50 dark:bg-emerald-500/10', alert: 'bg-amber-50 dark:bg-amber-500/10', system: 'bg-cyan-50 dark:bg-cyan-500/10',
}

const mockActivity: ActivityItem[] = [
  { id: '1', title: 'Document Processed', description: 'Q4 Financial Report 2024.pdf completed processing', timestamp: new Date(Date.now() - 120000).toISOString(), type: 'upload', status: 'success' },
  { id: '2', title: 'Query Executed', description: 'Complex hybrid retrieval query completed in 1.24s', timestamp: new Date(Date.now() - 300000).toISOString(), type: 'query', status: 'success' },
  { id: '3', title: 'Knowledge Updated', description: 'Version 8 deployed with 47 new documents', timestamp: new Date(Date.now() - 600000).toISOString(), type: 'update', status: 'success' },
  { id: '4', title: 'Hallucination Detected', description: 'Query confidence dropped below 0.65 threshold', timestamp: new Date(Date.now() - 900000).toISOString(), type: 'alert', status: 'warning' },
  { id: '5', title: 'Upload Failed', description: 'Vendor Contracts 2024.pdf failed OCR processing', timestamp: new Date(Date.now() - 1200000).toISOString(), type: 'upload', status: 'error' },
  { id: '6', title: 'System Reindex', description: 'Incremental reindex completed for Engineering docs', timestamp: new Date(Date.now() - 1800000).toISOString(), type: 'system', status: 'success' },
]

export function ActivityFeed({ items = mockActivity }: { items?: ActivityItem[] }) {
  return (
    <div className="space-y-1">
      {items.map((item, i) => (
        <motion.div key={item.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
          className="flex items-start gap-3 py-2.5 px-3 rounded-xl hover:bg-gray-50 dark:hover:bg-white/[0.03] transition-colors group">
          <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5', typeBg[item.type])}>
            <div className={cn('w-2 h-2 rounded-full', typeColors[item.type])} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-gray-800 dark:text-white/80 truncate">{item.title}</p>
              <span className="text-[10px] text-gray-400 dark:text-white/25 flex-shrink-0">{formatRelativeTime(item.timestamp)}</span>
            </div>
            <p className="text-[11px] text-gray-500 dark:text-white/40 mt-0.5 truncate">{item.description}</p>
          </div>
        </motion.div>
      ))}
    </div>
  )
}
