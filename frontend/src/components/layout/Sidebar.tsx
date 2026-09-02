'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, Upload, Search,
  Zap, Layers, MessageSquare, ShieldCheck, TrendingUp,
  Settings, ChevronLeft, ChevronRight, Brain, Ticket,
  ShieldAlert, Settings2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import { useRole } from '@/lib/usePermission'
import { hasPermission, hasAnyPermission, Permission } from '@/lib/rbac'

/**
 * Outer sidebar — top-level navigation.
 * Admin Panel is a single entry; sub-navigation lives in AdminSidebar
 * which is rendered by the /admin layout.
 */
const navItems = [
  { label: 'Dashboard',           href: '/dashboard',          icon: LayoutDashboard,  anyOf: undefined as Permission[] | undefined, permission: undefined as Permission | undefined },
  { label: 'Admin Panel',         href: '/admin/users',        icon: Settings2,        anyOf: [Permission.USER_READ, Permission.INGESTION_MONITOR, Permission.CHUNK_VIEW, Permission.LLM_VIEW, Permission.ANALYTICS_VIEW_PLATFORM] as Permission[], permission: undefined },
  { label: 'Knowledge Base',      href: '/ingestion',          icon: Upload,           anyOf: undefined, permission: Permission.DOCUMENT_UPLOAD },
  { label: 'Query Intelligence',  href: '/query-intelligence', icon: Search,           anyOf: undefined, permission: Permission.DOCUMENT_READ },
  { label: 'Adaptive Retrieval',  href: '/retrieval',          icon: Zap,              anyOf: undefined, permission: Permission.DOCUMENT_READ },
  { label: 'Context Fusion',      href: '/context-fusion',     icon: Layers,           anyOf: undefined, permission: Permission.DOCUMENT_READ },
  { label: 'Enterprise LLM',      href: '/llm',                icon: MessageSquare,    anyOf: undefined, permission: Permission.LLM_VIEW },
  { label: 'Evidence Check',      href: '/verification',       icon: ShieldCheck,      anyOf: undefined, permission: Permission.DOCUMENT_READ },
  { label: 'Continuous Learning', href: '/learning',           icon: TrendingUp,       anyOf: undefined, permission: Permission.ANALYTICS_VIEW_PLATFORM },
  { label: 'My Tickets',          href: '/tickets',            icon: Ticket,           anyOf: undefined, permission: Permission.TICKET_VIEW_OWN },
  { label: 'Security',            href: '/security',           icon: ShieldAlert,      anyOf: undefined, permission: undefined },
  { label: 'Settings',            href: '/settings',           icon: Settings,         anyOf: undefined, permission: undefined },
]

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useAppStore()
  const pathname = usePathname()
  const role = useRole()

  const visibleItems = navItems.filter(item => {
    if (item.anyOf) return hasAnyPermission(role, item.anyOf)
    if (item.permission) return hasPermission(role, item.permission)
    return true
  })

  return (
    <motion.aside
      animate={{ width: sidebarCollapsed ? 68 : 220 }}
      transition={{ duration: 0.25, ease: 'easeInOut' }}
      className="relative flex flex-col h-screen bg-white dark:bg-[#08080f] border-r border-gray-200 dark:border-white/[0.06] overflow-hidden flex-shrink-0 z-20"
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-gray-200 dark:border-white/[0.06]">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-blue-500/25">
          <Brain className="w-4 h-4 text-white" />
        </div>
        <AnimatePresence>
          {!sidebarCollapsed && (
            <motion.div initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.15 }}>
              <p className="text-sm font-bold text-gray-900 dark:text-white leading-tight">DAA-RAG</p>
              <p className="text-[10px] text-gray-400 dark:text-white/40 leading-tight">Enterprise Platform</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-3 no-scrollbar">
        {visibleItems.map((item) => {
          const Icon = item.icon
          const isAdminEntry = item.href.startsWith('/admin')
          const active = isAdminEntry
            ? pathname.startsWith('/admin')
            : (pathname === item.href || pathname.startsWith(item.href + '/'))
          return (
            <Link key={item.href} href={item.href}>
              <motion.div
                whileHover={{ x: sidebarCollapsed ? 0 : 2 }}
                className={cn(
                  'flex items-center gap-3 mx-2 px-3 py-2.5 rounded-xl mb-0.5 cursor-pointer transition-all duration-150 group',
                  active
                    ? 'bg-blue-50 dark:bg-gradient-to-r dark:from-blue-600/20 dark:to-violet-600/10 text-blue-700 dark:text-white border border-blue-200 dark:border-blue-500/20'
                    : 'text-gray-500 dark:text-white/50 hover:text-gray-800 dark:hover:text-white/80 hover:bg-gray-100 dark:hover:bg-white/[0.04]'
                )}
              >
                <Icon className={cn('w-4 h-4 flex-shrink-0 transition-colors',
                  active ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-white/40 group-hover:text-gray-600 dark:group-hover:text-white/60'
                )} />
                <AnimatePresence>
                  {!sidebarCollapsed && (
                    <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      className="text-xs font-medium whitespace-nowrap truncate">
                      {item.label}
                    </motion.span>
                  )}
                </AnimatePresence>
                {active && !sidebarCollapsed && (
                  <motion.div layoutId="activeIndicator" className="ml-auto w-1.5 h-1.5 rounded-full bg-blue-500 dark:bg-blue-400 flex-shrink-0" />
                )}
              </motion.div>
            </Link>
          )
        })}
      </nav>

      {/* Collapse toggle */}
      <button onClick={toggleSidebar}
        className="absolute -right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-white dark:bg-[#1a1a2e] border border-gray-200 dark:border-white/10 flex items-center justify-center text-gray-400 dark:text-white/40 hover:text-gray-700 dark:hover:text-white/80 hover:border-gray-300 dark:hover:border-white/20 transition-all z-30 shadow-sm">
        {sidebarCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
      </button>
    </motion.aside>
  )
}
