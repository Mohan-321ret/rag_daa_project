import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export function formatNumber(num: number): string {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toString()
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

export function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    completed: 'text-emerald-400',
    processing: 'text-blue-400',
    failed: 'text-red-400',
    queued: 'text-amber-400',
    active: 'text-emerald-400',
    inactive: 'text-gray-400',
    syncing: 'text-blue-400',
    success: 'text-emerald-400',
    warning: 'text-amber-400',
    error: 'text-red-400',
  }
  return map[status] ?? 'text-gray-400'
}

export function getConfidenceColor(score: number): string {
  if (score >= 0.9) return 'text-emerald-400'
  if (score >= 0.7) return 'text-blue-400'
  if (score >= 0.5) return 'text-amber-400'
  return 'text-red-400'
}

export function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
