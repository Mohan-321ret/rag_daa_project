'use client'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface StatCardProps {
  title: string
  value: string | number
  subtitle?: string
  trend?: number
  icon: React.ReactNode
  accentColor?: string
  delay?: number
  suffix?: string
}

export function StatCard({ title, value, subtitle, trend, icon, accentColor = 'text-blue-500', delay = 0, suffix }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay }}
      whileHover={{ y: -2, transition: { duration: 0.15 } }}
      className="adaptive-card p-5 group cursor-default"
    >
      <div className="flex items-start justify-between mb-4">
        <div className={cn('w-9 h-9 rounded-xl bg-current/10 flex items-center justify-center', accentColor)}>
          <div className="opacity-80">{icon}</div>
        </div>
        {trend !== undefined && (
          <div className={cn('flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-lg',
            trend > 0 ? 'text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-400/10'
              : trend < 0 ? 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-400/10'
              : 'text-gray-500 bg-gray-100 dark:text-white/40 dark:bg-white/[0.05]'
          )}>
            {trend > 0 ? <TrendingUp className="w-3 h-3" /> : trend < 0 ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
            {Math.abs(trend)}%
          </div>
        )}
      </div>
      <p className="text-2xl font-bold text-adaptive-primary tracking-tight">
        {value}{suffix && <span className="text-sm font-normal text-adaptive-muted ml-1">{suffix}</span>}
      </p>
      <p className="text-xs text-adaptive-secondary mt-1 font-medium">{title}</p>
      {subtitle && <p className="text-[11px] text-adaptive-muted mt-0.5">{subtitle}</p>}
    </motion.div>
  )
}
