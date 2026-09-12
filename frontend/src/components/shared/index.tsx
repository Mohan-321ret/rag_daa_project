'use client'
import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePermission } from '@/lib/usePermission'
import type { Permission } from '@/lib/rbac'

interface StatusBadgeProps { status: string; size?: 'sm' | 'md' }

const statusConfig: Record<string, { label: string; dot: string; cls: string }> = {
  completed:    { label: 'Completed',  dot: 'bg-emerald-500',                cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400' },
  indexed:      { label: 'Completed',  dot: 'bg-emerald-500',                cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400' },
  processing:   { label: 'Processing', dot: 'bg-blue-500 animate-pulse',     cls: 'bg-blue-50 text-blue-700 dark:bg-blue-400/10 dark:text-blue-400' },
  failed:       { label: 'Failed',     dot: 'bg-red-500',                    cls: 'bg-red-50 text-red-700 dark:bg-red-400/10 dark:text-red-400' },
  queued:       { label: 'Queued',     dot: 'bg-amber-500',                  cls: 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400' },
  cancelled:    { label: 'Cancelled',  dot: 'bg-gray-400',                   cls: 'bg-gray-100 text-gray-500 dark:bg-gray-500/10 dark:text-gray-400' },
  active:       { label: 'Active',     dot: 'bg-emerald-500 animate-pulse',  cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400' },
  inactive:     { label: 'Inactive',   dot: 'bg-gray-400',                   cls: 'bg-gray-100 text-gray-500 dark:bg-gray-500/10 dark:text-gray-400' },
  syncing:      { label: 'Syncing',    dot: 'bg-blue-500 animate-pulse',     cls: 'bg-blue-50 text-blue-700 dark:bg-blue-400/10 dark:text-blue-400' },
  success:      { label: 'Success',    dot: 'bg-emerald-500',                cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400' },
  warning:      { label: 'Warning',    dot: 'bg-amber-500',                  cls: 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400' },
  error:        { label: 'Error',      dot: 'bg-red-500',                    cls: 'bg-red-50 text-red-700 dark:bg-red-400/10 dark:text-red-400' },
  stable:       { label: 'Stable',     dot: 'bg-emerald-500',                cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400' },
  current:      { label: 'Current',    dot: 'bg-blue-500',                   cls: 'bg-blue-50 text-blue-700 dark:bg-blue-400/10 dark:text-blue-400' },
  deprecated:   { label: 'Deprecated', dot: 'bg-gray-400',                   cls: 'bg-gray-100 text-gray-500 dark:bg-gray-500/10 dark:text-gray-400' },
  pending:      { label: 'Pending',    dot: 'bg-amber-500',                  cls: 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400' },
  not_required: { label: 'N/A',        dot: 'bg-gray-400',                   cls: 'bg-gray-100 text-gray-400 dark:bg-gray-500/10 dark:text-gray-400' },
}

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const c = statusConfig[status] ?? { label: status, dot: 'bg-gray-400', cls: 'bg-gray-100 text-gray-500 dark:bg-gray-500/10 dark:text-gray-400' }
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full font-medium', c.cls,
      size === 'sm' ? 'text-[10px] px-2 py-0.5' : 'text-xs px-2.5 py-1')}>
      <span className={cn('rounded-full flex-shrink-0', c.dot, size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2')} />
      {c.label}
    </span>
  )
}

interface ConfidenceMeterProps { value: number; showLabel?: boolean; size?: 'sm' | 'md' | 'lg' }

export function ConfidenceMeter({ value, showLabel = true, size = 'md' }: ConfidenceMeterProps) {
  const pct = Math.round(value * 100)
  const bar = value >= 0.9 ? 'from-emerald-500 to-emerald-400' : value >= 0.7 ? 'from-blue-500 to-blue-400' : value >= 0.5 ? 'from-amber-500 to-amber-400' : 'from-red-500 to-red-400'
  const txt = value >= 0.9 ? 'text-emerald-600 dark:text-emerald-400' : value >= 0.7 ? 'text-blue-600 dark:text-blue-400' : value >= 0.5 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'
  const h = size === 'sm' ? 'h-1' : size === 'lg' ? 'h-2.5' : 'h-1.5'
  return (
    <div className="flex items-center gap-2">
      <div className={cn('flex-1 bg-gray-200 dark:bg-white/[0.06] rounded-full overflow-hidden', h)}>
        <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.8, ease: 'easeOut' }}
          className={cn('h-full rounded-full bg-gradient-to-r', bar)} />
      </div>
      {showLabel && <span className={cn('text-xs font-semibold tabular-nums', txt)}>{pct}%</span>}
    </div>
  )
}

export function ConfidenceBadge({ value, size = 'sm' }: { value: number | null | undefined; size?: 'sm' | 'md' }) {
  if (value === null || value === undefined) return null
  const pct = Math.round(value * 100)
  
  let label = 'Low'
  let bg = 'bg-red-50 dark:bg-red-500/15 border-red-200 dark:border-red-500/30 text-red-600 dark:text-red-400'
  let dot = 'bg-red-500 dark:bg-red-400'
  
  if (pct >= 80) {
    label = 'High'
    bg = 'bg-emerald-50 dark:bg-emerald-500/15 border-emerald-200 dark:border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
    dot = 'bg-emerald-500 dark:bg-emerald-400'
  } else if (pct >= 60) {
    label = 'Medium'
    bg = 'bg-amber-50 dark:bg-amber-500/15 border-amber-200 dark:border-amber-500/30 text-amber-600 dark:text-amber-400'
    dot = 'bg-amber-500 dark:bg-amber-400'
  }

  const padding = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'

  return (
    <span className={cn('inline-flex items-center gap-1.5 font-medium border rounded-full', bg, padding)}>
      <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', dot)} />
      <span>{pct}% ({label})</span>
    </span>
  )
}

export function LoadingSkeleton({ className }: { className?: string }) {
  return <div className={cn('rounded-lg bg-gray-200 dark:bg-white/[0.04] shimmer-bg animate-pulse', className)} />
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-8">
      <div>
        <h1 className="text-2xl font-bold text-adaptive-primary tracking-tight">{title}</h1>
        {description && <p className="text-sm text-adaptive-secondary mt-1">{description}</p>}
      </div>
      {children && <div className="flex items-center gap-3">{children}</div>}
    </div>
  )
}

export function Card({ children, className, hover = false }: { children: React.ReactNode; className?: string; hover?: boolean }) {
  return (
    <motion.div whileHover={hover ? { y: -2 } : undefined} transition={{ duration: 0.15 }}
      className={cn('adaptive-card p-5', className)}>
      {children}
    </motion.div>
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs font-semibold text-adaptive-secondary uppercase tracking-wider mb-4">{children}</h2>
}

/**
 * Renders `children` only if the current user's role holds `permission`
 * (RBAC Foundation — see lib/rbac.ts). Pass an array + `any` to require just
 * one of several permissions instead of all of them. UX-only: the backend
 * independently enforces the real check on every request this gates.
 */
export function Can({
  permission, any, children, fallback = null,
}: {
  permission: Permission | Permission[]
  any?: boolean
  children: React.ReactNode
  fallback?: React.ReactNode
}) {
  const allowed = usePermission(permission, { any })
  return <>{allowed ? children : fallback}</>
}

export function EmptyState({ icon, title, description }: { icon: React.ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-2xl bg-gray-100 dark:bg-white/[0.05] flex items-center justify-center text-gray-400 dark:text-white/30 mb-4">
        {icon}
      </div>
      <p className="text-sm font-semibold text-adaptive-primary">{title}</p>
      {description && <p className="text-xs text-adaptive-muted mt-1 max-w-xs">{description}</p>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-10 h-10 rounded-xl bg-red-50 dark:bg-red-500/10 flex items-center justify-center text-red-500 mb-3">⚠</div>
      <p className="text-sm font-medium text-adaptive-primary">{message}</p>
      {onRetry && <button onClick={onRetry} className="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:underline">Try again</button>}
    </div>
  )
}

/**
 * Self-contained modal (backdrop + Escape-to-close), no Radix dependency.
 * `open` is fully controlled by the caller — this component renders nothing
 * when `open` is false so it's safe to always mount.
 */
export function Modal({
  open, onClose, title, children, maxWidth = 'max-w-md',
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  maxWidth?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }} transition={{ duration: 0.15 }}
            className={cn('relative w-full bg-white dark:bg-[#12121c] border border-gray-200 dark:border-white/[0.08] rounded-2xl shadow-2xl max-h-[85vh] overflow-y-auto', maxWidth)}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-white/[0.06] sticky top-0 bg-white dark:bg-[#12121c] rounded-t-2xl">
              <h3 className="text-sm font-semibold text-adaptive-primary">{title}</h3>
              <button onClick={onClose} className="text-gray-400 dark:text-white/30 hover:text-gray-700 dark:hover:text-white/70 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

/** Confirmation dialog for destructive/irreversible actions. */
export function ConfirmDialog({
  open, onClose, onConfirm, title, description, confirmLabel = 'Confirm', danger = true, loading = false,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description: string
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} maxWidth="max-w-sm">
      <div className="flex gap-3 mb-5">
        {danger && (
          <div className="w-9 h-9 rounded-xl bg-red-50 dark:bg-red-500/10 flex items-center justify-center text-red-500 flex-shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
        )}
        <p className="text-sm text-adaptive-secondary leading-relaxed">{description}</p>
      </div>
      <div className="flex items-center justify-end gap-2">
        <Btn variant="ghost" size="sm" onClick={onClose} disabled={loading}>Cancel</Btn>
        <Btn variant={danger ? 'danger' : 'primary'} size="sm" onClick={onConfirm} disabled={loading}>
          {loading ? 'Working…' : confirmLabel}
        </Btn>
      </div>
    </Modal>
  )
}

export function Btn({ children, variant = 'primary', size = 'md', onClick, disabled, className }: {
  children: React.ReactNode; variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'; onClick?: () => void; disabled?: boolean; className?: string
}) {
  const base = 'inline-flex items-center gap-2 font-semibold rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed'
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm' }
  const variants = {
    primary: 'bg-gradient-to-r from-blue-600 to-violet-600 text-white hover:from-blue-500 hover:to-violet-500 shadow-sm',
    secondary: 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-white/[0.06] dark:text-white/70 dark:hover:bg-white/[0.1]',
    ghost: 'border border-gray-200 text-gray-600 hover:bg-gray-50 dark:border-white/[0.08] dark:text-white/60 dark:hover:bg-white/[0.04]',
    danger: 'bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-500/10 dark:text-red-400 dark:hover:bg-red-500/20',
  }
  return (
    <motion.button whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.98 }}
      onClick={onClick} disabled={disabled}
      className={cn(base, sizes[size], variants[variant], className)}>
      {children}
    </motion.button>
  )
}
