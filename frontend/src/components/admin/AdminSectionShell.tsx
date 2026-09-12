'use client'
/**
 * AdminSectionShell — Consistent page wrapper for every Admin Panel sub-page.
 *
 * Provides:
 *  - Breadcrumb trail (Home > Admin Panel > Section > Sub-page)
 *  - H1 title + subtitle
 *  - Optional action slot (right-side button, e.g. "Invite User")
 *  - Consistent page padding and spacing
 */
import { ChevronRight, LayoutDashboard } from 'lucide-react'
import Link from 'next/link'
import { motion } from 'framer-motion'

interface BreadcrumbItem {
  label: string
  href?: string
}

interface AdminSectionShellProps {
  title: string
  description?: string
  breadcrumbs?: BreadcrumbItem[]   // auto-prepends "Admin Panel" if not provided
  action?: React.ReactNode
  children: React.ReactNode
  badge?: React.ReactNode
}

export function AdminSectionShell({
  title,
  description,
  breadcrumbs,
  action,
  children,
  badge,
}: AdminSectionShellProps) {
  const crumbs: BreadcrumbItem[] = breadcrumbs ?? [{ label: 'Admin Panel', href: '/admin' }, { label: title }]

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="space-y-6"
    >
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-white/35">
        <Link href="/dashboard" className="hover:text-gray-900 dark:hover:text-white/60 transition-colors flex items-center gap-1">
          <LayoutDashboard className="w-3 h-3" />
        </Link>
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <ChevronRight className="w-3 h-3 text-gray-400 dark:text-white/20" />
            {crumb.href ? (
              <Link href={crumb.href} className="hover:text-gray-900 dark:hover:text-white/60 transition-colors">{crumb.label}</Link>
            ) : (
              <span className="text-gray-700 dark:text-white/60 font-medium">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold text-gray-900 dark:text-white tracking-tight">{title}</h1>
              {badge}
            </div>
            {description && (
              <p className="text-sm text-gray-500 dark:text-white/40 mt-0.5">{description}</p>
            )}
          </div>
        </div>
        {action && <div className="flex-shrink-0">{action}</div>}
      </div>

      {/* Content */}
      <div>{children}</div>
    </motion.div>
  )
}
