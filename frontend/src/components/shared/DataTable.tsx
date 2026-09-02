'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { EmptyState } from './index'
import { FileText } from 'lucide-react'

interface Column<T> {
  key: keyof T | string
  label: string
  render?: (value: unknown, row: T) => React.ReactNode
  sortable?: boolean
  width?: string
}

interface DataTableProps<T> {
  data: T[]
  columns: Column<T>[]
  onRowClick?: (row: T) => void
  emptyMessage?: string
  loading?: boolean
}

export function DataTable<T extends { id: string }>({ data, columns, onRowClick, emptyMessage = 'No data available', loading }: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSort = (key: string) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const sorted = [...data].sort((a, b) => {
    if (!sortKey) return 0
    const av = (a as Record<string, unknown>)[sortKey]
    const bv = (b as Record<string, unknown>)[sortKey]
    if (av === undefined || bv === undefined) return 0
    return sortDir === 'asc' ? String(av).localeCompare(String(bv), undefined, { numeric: true }) : String(bv).localeCompare(String(av), undefined, { numeric: true })
  })

  if (loading) return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-12 rounded-xl bg-gray-100 dark:bg-white/[0.03] animate-pulse" />
      ))}
    </div>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-200 dark:border-white/[0.06]">
            {columns.map(col => (
              <th key={String(col.key)} className={cn('text-left py-3 px-4 text-[11px] font-semibold text-gray-500 dark:text-white/40 uppercase tracking-wider whitespace-nowrap', col.width)}>
                {col.sortable ? (
                  <button onClick={() => handleSort(String(col.key))} className="flex items-center gap-1 hover:text-gray-800 dark:hover:text-white/70 transition-colors">
                    {col.label}
                    {sortKey === col.key ? (sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />) : <ChevronsUpDown className="w-3 h-3 opacity-40" />}
                  </button>
                ) : col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr><td colSpan={columns.length}><EmptyState icon={<FileText className="w-5 h-5" />} title={emptyMessage} /></td></tr>
          ) : sorted.map((row, i) => (
            <motion.tr key={row.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }}
              onClick={() => onRowClick?.(row)}
              className={cn('border-b border-gray-100 dark:border-white/[0.04] transition-colors', onRowClick && 'cursor-pointer hover:bg-gray-50 dark:hover:bg-white/[0.02]')}>
              {columns.map(col => (
                <td key={String(col.key)} className="py-3 px-4 text-xs text-gray-700 dark:text-white/70">
                  {col.render ? col.render((row as Record<string, unknown>)[String(col.key)], row) : String((row as Record<string, unknown>)[String(col.key)] ?? '')}
                </td>
              ))}
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
