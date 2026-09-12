'use client'
/**
 * AdminSidebar — The 8-section inner navigation for the Admin Panel.
 *
 * Each section is a collapsible group with permission-gated sub-items.
 * Sections whose items are ALL hidden (user lacks all permissions) are
 * completely omitted — no empty headers.
 *
 * Permission matrix mirrors backend/app/core/permissions.py exactly.
 */
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Users, ShieldCheck, KeyRound, Globe2, UserCog, Lock,
  Upload, Briefcase, AlertCircle, RefreshCw,
  Boxes, BarChart2, Cpu, Plug, Zap,
  FileSearch, Clock, TrendingUp,
  Ticket, CheckCircle, Inbox, UserCheck,
  LineChart, Activity, Gauge,
  ScrollText, ChevronDown, ChevronRight, Settings2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { hasPermission, hasAnyPermission, type Permission, type Role } from '@/lib/rbac'
import { useRole } from '@/lib/usePermission'
import { Permission as P } from '@/lib/rbac'

// ── Navigation structure ───────────────────────────────────────────────────────
interface NavItem {
  label: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  permission?: Permission
}

interface NavSection {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  color: string        // Tailwind color class for section accent
  items: NavItem[]
  anyPermission?: Permission[]  // show section if user has ANY of these
}

const SECTIONS: NavSection[] = [
  {
    id: 'access',
    label: 'User & Access Management',
    icon: Users,
    color: 'text-blue-400',
    anyPermission: [P.USER_READ, P.DOMAIN_MANAGE, P.PERMISSION_MANAGE, P.ROLE_ASSIGN, P.DOMAIN_ASSIGN],
    items: [
      { label: 'Users',               href: '/admin/users',              icon: Users,     permission: P.USER_READ },
      { label: 'Roles',               href: '/admin/roles',              icon: ShieldCheck, permission: P.ROLE_ASSIGN },
      { label: 'Permissions',         href: '/admin/permissions',        icon: KeyRound,  permission: P.PERMISSION_MANAGE },
      { label: 'Domains',             href: '/admin/domains',            icon: Globe2,    permission: P.DOMAIN_MANAGE },
      { label: 'User-domain assignments', href: '/admin/domain-assignments', icon: UserCog, permission: P.DOMAIN_ASSIGN },
      { label: 'Access Policies',     href: '/admin/access-policies',    icon: Lock,      permission: P.PERMISSION_MANAGE },
    ],
  },
  {
    id: 'ingestion',
    label: 'Data Injection',
    icon: Upload,
    color: 'text-emerald-400',
    anyPermission: [P.INGESTION_MONITOR, P.DOCUMENT_UPLOAD],
    items: [
      { label: 'Upload',              href: '/admin/ingestion',          icon: Upload,    permission: P.DOCUMENT_UPLOAD },
      { label: 'Ingestion Jobs',      href: '/admin/ingestion?tab=jobs', icon: Briefcase, permission: P.INGESTION_MONITOR },
      { label: 'Processing Status',   href: '/admin/ingestion?tab=status', icon: Activity, permission: P.INGESTION_MONITOR },
      { label: 'Failed Jobs',         href: '/admin/ingestion?tab=failed', icon: AlertCircle, permission: P.INGESTION_MONITOR },
      { label: 'Retry',               href: '/admin/ingestion?tab=retry', icon: RefreshCw, permission: P.INGESTION_RETRY },
    ],
  },
  {
    id: 'chunks',
    label: 'Chunk Indexing Management',
    icon: Boxes,
    color: 'text-cyan-400',
    anyPermission: [P.CHUNK_VIEW, P.CHUNK_REINDEX],
    items: [
      { label: 'Chunk Explorer',      href: '/admin/chunk-indexing',              icon: Boxes,      permission: P.CHUNK_VIEW },
      { label: 'Index Status',        href: '/admin/chunk-indexing?tab=status',   icon: BarChart2,  permission: P.CHUNK_VIEW },
      { label: 'Re-index',            href: '/admin/chunk-indexing?tab=reindex',  icon: RefreshCw,  permission: P.CHUNK_REINDEX },
      { label: 'Failed Chunks',       href: '/admin/chunk-indexing?tab=failed',   icon: AlertCircle, permission: P.CHUNK_VIEW },
      { label: 'Stale Chunks',        href: '/admin/chunk-indexing?tab=stale',    icon: Clock,      permission: P.CHUNK_VIEW },
    ],
  },
  {
    id: 'llm',
    label: 'LLM Management',
    icon: Cpu,
    color: 'text-violet-400',
    anyPermission: [P.LLM_VIEW, P.LLM_CONFIGURE],
    items: [
      { label: 'Providers',           href: '/admin/llm',               icon: Plug,      permission: P.LLM_VIEW },
      { label: 'Models',              href: '/admin/llm?tab=models',    icon: Cpu,       permission: P.LLM_VIEW },
      { label: 'Active Model',        href: '/admin/llm?tab=active',    icon: Zap,       permission: P.LLM_VIEW },
      { label: 'Configuration',       href: '/admin/llm?tab=config',    icon: Settings2, permission: P.LLM_CONFIGURE },
      { label: 'Connection Test',     href: '/admin/llm?tab=test',      icon: Activity,  permission: P.LLM_CONFIGURE },
    ],
  },
  {
    id: 'queries',
    label: 'Query Management',
    icon: FileSearch,
    color: 'text-amber-400',
    anyPermission: [P.QUERY_LOG_VIEW_GLOBAL, P.QUERY_LOG_VIEW_DOMAIN, P.ANALYTICS_VIEW_PLATFORM],
    items: [
      { label: 'Query Logs',          href: '/admin/query-logs',         icon: ScrollText, permission: P.QUERY_LOG_VIEW_GLOBAL },
      { label: 'Query History',       href: '/admin/query-logs?tab=history', icon: Clock, permission: P.QUERY_LOG_VIEW_DOMAIN },
      { label: 'Query Analytics',     href: '/admin/query-analytics',    icon: TrendingUp, permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'Retrieval Traces',    href: '/admin/retrieval-traces',   icon: Zap,        permission: P.QUERY_LOG_VIEW_GLOBAL },
    ],
  },
  {
    id: 'tickets',
    label: 'Ticket Management',
    icon: Ticket,
    color: 'text-rose-400',
    anyPermission: [P.TICKET_VIEW_DOMAIN, P.TICKET_ASSIGN, P.TICKET_RESOLVE],
    items: [
      { label: 'All Tickets',         href: '/admin/tickets',                  icon: Ticket,      permission: P.TICKET_VIEW_DOMAIN },
      { label: 'Domain Queues',       href: '/admin/tickets?tab=domains',      icon: Globe2,      permission: P.TICKET_VIEW_DOMAIN },
      { label: 'Assigned Tickets',    href: '/admin/tickets?tab=assigned',     icon: UserCheck,   permission: P.TICKET_ASSIGN },
      { label: 'Unassigned Tickets',  href: '/admin/tickets?tab=unassigned',   icon: Inbox,       permission: P.TICKET_VIEW_DOMAIN },
      { label: 'Resolved Tickets',    href: '/admin/tickets?tab=resolved',     icon: CheckCircle, permission: P.TICKET_VIEW_DOMAIN },
    ],
  },
  {
    id: 'analytics',
    label: 'Analytics',
    icon: LineChart,
    color: 'text-teal-400',
    anyPermission: [P.ANALYTICS_VIEW_PLATFORM, P.ANALYTICS_VIEW_DOMAIN],
    items: [
      { label: 'Retrieval Accuracy',  href: '/admin/analytics',                icon: Gauge,      permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'Confidence',          href: '/admin/analytics?tab=confidence', icon: BarChart2,  permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'Hallucination Rate',  href: '/admin/analytics?tab=hallucination', icon: AlertCircle, permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'Ticket Statistics',   href: '/admin/analytics?tab=tickets',    icon: Ticket,     permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'Latency',             href: '/admin/analytics?tab=latency',    icon: Clock,      permission: P.ANALYTICS_VIEW_PLATFORM },
      { label: 'User Satisfaction',   href: '/admin/analytics?tab=satisfaction', icon: TrendingUp, permission: P.ANALYTICS_VIEW_PLATFORM },
    ],
  },
  {
    id: 'audit',
    label: 'Audit Logs',
    icon: ScrollText,
    color: 'text-orange-400',
    anyPermission: [P.QUERY_LOG_VIEW_GLOBAL, P.PERMISSION_MANAGE, P.USER_READ],
    items: [
      { label: 'user changes',        href: '/admin/audit-logs',                icon: Users,       permission: P.USER_READ },
      { label: 'permission changes',  href: '/admin/audit-logs?tab=permissions', icon: KeyRound,   permission: P.PERMISSION_MANAGE },
      { label: 'document actions',    href: '/admin/audit-logs?tab=documents',  icon: FileSearch,  permission: P.QUERY_LOG_VIEW_GLOBAL },
      { label: 'indexing actions',    href: '/admin/audit-logs?tab=indexing',   icon: Boxes,       permission: P.INGESTION_MONITOR },
      { label: 'LLM changes',         href: '/admin/audit-logs?tab=llm',        icon: Cpu,         permission: P.QUERY_LOG_VIEW_GLOBAL },
      { label: 'ticket actions',      href: '/admin/audit-logs?tab=tickets',    icon: Ticket,      permission: P.QUERY_LOG_VIEW_GLOBAL },
    ],
  },
]

// ── Component ──────────────────────────────────────────────────────────────────
export function AdminSidebar() {
  const pathname = usePathname()
  const role = useRole()

  // Track which sections are expanded; default: expand the active section
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  // Auto-expand the section containing the current route
  useEffect(() => {
    const activeSection = SECTIONS.find(s =>
      s.items.some(item => pathname === item.href || pathname.startsWith(item.href.split('?')[0]))
    )
    if (activeSection) {
      setExpanded(prev => ({ ...prev, [activeSection.id]: true }))
    }
  }, [pathname])

  const toggle = (id: string) =>
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }))

  const visibleSections = SECTIONS.filter(section => {
    if (!section.anyPermission) return true
    return hasAnyPermission(role, section.anyPermission)
  })

  return (
    <aside className="w-56 flex-shrink-0 h-full bg-white dark:bg-[#07070e]/80 border-r border-gray-200 dark:border-white/[0.05] overflow-y-auto no-scrollbar">
      {/* Admin Panel header */}
      <div className="px-4 py-4 border-b border-gray-200 dark:border-white/[0.05]">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center flex-shrink-0">
            <Settings2 className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-gray-900 dark:text-white">Admin Panel</span>
        </div>
      </div>

      {/* Sections */}
      <nav className="py-3 px-2 space-y-0.5">
        {visibleSections.map(section => {
          const SectionIcon = section.icon
          const isOpen = expanded[section.id] ?? false

          const visibleItems = section.items.filter(item =>
            !item.permission || hasPermission(role, item.permission)
          )
          if (visibleItems.length === 0) return null

          const sectionActive = visibleItems.some(
            item => pathname === item.href || pathname.startsWith(item.href.split('?')[0])
          )

          return (
            <div key={section.id}>
              {/* Section header */}
              <button
                onClick={() => toggle(section.id)}
                className={cn(
                  'w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold uppercase tracking-wider transition-all',
                  sectionActive
                    ? 'text-gray-900 dark:text-white/90 bg-gray-100 dark:bg-white/[0.05]'
                    : 'text-gray-500 dark:text-white/35 hover:text-gray-900 dark:hover:text-white/60 hover:bg-gray-50 dark:hover:bg-white/[0.03]'
                )}
              >
                <SectionIcon className={cn('w-3.5 h-3.5 flex-shrink-0', section.color)} />
                <span className="flex-1 text-left">{section.label}</span>
                <motion.div animate={{ rotate: isOpen ? 180 : 0 }} transition={{ duration: 0.15 }}>
                  <ChevronDown className="w-3 h-3 text-gray-400 dark:text-white/25" />
                </motion.div>
              </button>

              {/* Sub-items */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.18, ease: 'easeInOut' }}
                    className="overflow-hidden"
                  >
                    <div className="ml-2 pl-3 border-l border-gray-200 dark:border-white/[0.06] mt-0.5 mb-1 space-y-0.5">
                      {visibleItems.map(item => {
                        const ItemIcon = item.icon
                        const isActive = pathname === item.href || pathname.startsWith(item.href.split('?')[0])
                        return (
                          <Link key={item.href} href={item.href}>
                            <motion.div
                              whileHover={{ x: 2 }}
                              className={cn(
                                'flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all group',
                                isActive
                                  ? 'bg-blue-50 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-500/20'
                                  : 'text-gray-600 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70 hover:bg-gray-100 dark:hover:bg-white/[0.04]'
                              )}
                            >
                              <ItemIcon className={cn(
                                'w-3.5 h-3.5 flex-shrink-0',
                                isActive ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-white/30 group-hover:text-gray-600 dark:group-hover:text-white/50'
                              )} />
                              {item.label}
                              {isActive && (
                                <motion.div
                                  layoutId={`admin-active-${section.id}`}
                                  className="ml-auto w-1 h-1 rounded-full bg-blue-600 dark:bg-blue-400 flex-shrink-0"
                                />
                              )}
                            </motion.div>
                          </Link>
                        )
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
