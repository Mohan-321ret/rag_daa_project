'use client'
import { usePathname, useRouter } from 'next/navigation'
import { Bell, Search, Sun, Moon, ChevronDown, Check, Building2, X } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useAppStore } from '@/store/appStore'
import { cn, formatRelativeTime } from '@/lib/utils'

const breadcrumbMap: Record<string, string> = {
  '/dashboard': 'Dashboard', '/ingestion': 'Knowledge Ingestion', '/processing': 'Document Processing',
  '/evolution': 'Knowledge Evolution', '/repository': 'Knowledge Repository',
  '/query-intelligence': 'Query Intelligence', '/retrieval': 'Adaptive Retrieval',
  '/context-fusion': 'Context Fusion', '/llm': 'Enterprise LLM', '/verification': 'Evidence Verification',
  '/learning': 'Continuous Learning', '/security': 'Security & Governance', '/monitor': 'System Monitor',
  '/query-history': 'Query History', '/settings': 'Settings', '/documents': 'Document Details',
}
const workspaces = ['Enterprise HQ', 'R&D Division', 'Finance Dept', 'Legal Team']

export function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { theme, setTheme } = useTheme()
  const { notifications, clearNotifications, activeWorkspace, setActiveWorkspace, currentUser, logout } = useAppStore()
  const [showNotifs, setShowNotifs] = useState(false)
  const [showWorkspace, setShowWorkspace] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const unread = notifications.filter(n => !n.read).length
  const pageTitle = breadcrumbMap[pathname] ?? 'Dashboard'

  const dropdownCls = 'absolute right-0 top-11 bg-white dark:bg-[#12121f] border border-gray-200 dark:border-white/10 rounded-2xl shadow-xl dark:shadow-2xl overflow-hidden z-50'

  return (
    <header className="h-14 border-b border-gray-200 dark:border-white/[0.06] bg-white/80 dark:bg-[#08080f]/80 backdrop-blur-xl flex items-center px-6 gap-4 sticky top-0 z-10">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="text-gray-400 dark:text-white/30 text-sm hidden sm:block">DAA-RAG</span>
        <span className="text-gray-300 dark:text-white/20 text-sm hidden sm:block">/</span>
        <span className="text-gray-700 dark:text-white/80 text-sm font-semibold truncate">{pageTitle}</span>
      </div>

      {/* Search */}
      <div className="hidden md:flex items-center gap-2 bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-1.5 w-56 focus-within:border-blue-400 dark:focus-within:border-blue-500/50 transition-all">
        <Search className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
        <input placeholder="Search anything..." className="bg-transparent text-xs text-gray-700 dark:text-white/60 placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none w-full" />
        <kbd className="text-[10px] text-gray-400 dark:text-white/20 bg-gray-200 dark:bg-white/[0.06] px-1.5 py-0.5 rounded hidden lg:block">⌘K</kbd>
      </div>

      {/* Workspace */}
      <div className="relative">
        <button onClick={() => { setShowWorkspace(!showWorkspace); setShowNotifs(false); setShowProfile(false) }}
          className="flex items-center gap-2 bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-1.5 text-xs text-gray-600 dark:text-white/60 hover:text-gray-900 dark:hover:text-white/80 hover:border-gray-300 dark:hover:border-white/15 transition-all">
          <Building2 className="w-3.5 h-3.5" />
          <span className="hidden sm:block max-w-[100px] truncate">{activeWorkspace}</span>
          <ChevronDown className="w-3 h-3" />
        </button>
        <AnimatePresence>
          {showWorkspace && (
            <motion.div initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.97 }}
              className={cn(dropdownCls, 'w-48')}>
              <div className="px-3 py-2 border-b border-gray-100 dark:border-white/[0.06]">
                <p className="text-[10px] font-semibold text-gray-400 dark:text-white/30 uppercase tracking-wider">Workspaces</p>
              </div>
              {workspaces.map(w => (
                <button key={w} onClick={() => { setActiveWorkspace(w); setShowWorkspace(false) }}
                  className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-gray-600 dark:text-white/60 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-white/[0.05] transition-all">
                  {w} {w === activeWorkspace && <Check className="w-3 h-3 text-blue-500 dark:text-blue-400" />}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Theme */}
      <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        className="w-8 h-8 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] flex items-center justify-center text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/80 hover:border-gray-300 dark:hover:border-white/15 transition-all">
        {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
      </button>

      {/* Notifications */}
      <div className="relative">
        <button onClick={() => { setShowNotifs(!showNotifs); setShowWorkspace(false); setShowProfile(false) }}
          className="relative w-8 h-8 rounded-xl bg-gray-100 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] flex items-center justify-center text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/80 hover:border-gray-300 dark:hover:border-white/15 transition-all">
          <Bell className="w-3.5 h-3.5" />
          {unread > 0 && <span className="absolute -top-1 -right-1 w-4 h-4 bg-blue-500 rounded-full text-[9px] text-white flex items-center justify-center font-bold">{unread}</span>}
        </button>
        <AnimatePresence>
          {showNotifs && (
            <motion.div initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.97 }}
              className={cn(dropdownCls, 'w-80')}>
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-white/[0.06]">
                <span className="text-xs font-semibold text-gray-800 dark:text-white">Notifications</span>
                <button onClick={clearNotifications} className="text-[10px] text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300">Mark all read</button>
              </div>
              <div className="max-h-72 overflow-y-auto">
                {notifications.map(n => (
                  <div key={n.id} className={cn('px-4 py-3 border-b border-gray-50 dark:border-white/[0.04] hover:bg-gray-50 dark:hover:bg-white/[0.03] transition-all', !n.read && 'bg-blue-50/50 dark:bg-blue-500/[0.04]')}>
                    <div className="flex items-start gap-2">
                      <div className={cn('w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0', { 'bg-emerald-500': n.type === 'success', 'bg-blue-500': n.type === 'info', 'bg-amber-500': n.type === 'warning', 'bg-red-500': n.type === 'error' })} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold text-gray-800 dark:text-white/80">{n.title}</p>
                        <p className="text-[11px] text-gray-500 dark:text-white/40 mt-0.5 leading-tight">{n.message}</p>
                        <p className="text-[10px] text-gray-400 dark:text-white/25 mt-1">{formatRelativeTime(n.timestamp)}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Profile */}
      <div className="relative">
        <button onClick={() => { setShowProfile(!showProfile); setShowNotifs(false); setShowWorkspace(false) }}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center text-[11px] font-bold text-white shadow-sm">
            {currentUser?.name.split(' ').map(n => n[0]).join('')}
          </div>
          <ChevronDown className="w-3 h-3 text-gray-400 dark:text-white/30" />
        </button>
        <AnimatePresence>
          {showProfile && (
            <motion.div initial={{ opacity: 0, y: -6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.97 }}
              className={cn(dropdownCls, 'w-52')}>
              <div className="px-4 py-3 border-b border-gray-100 dark:border-white/[0.06]">
                <p className="text-xs font-semibold text-gray-800 dark:text-white">{currentUser?.name}</p>
                <p className="text-[11px] text-gray-500 dark:text-white/40 truncate">{currentUser?.email}</p>
                <span className="inline-block mt-1 text-[10px] bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 px-2 py-0.5 rounded-full capitalize">{currentUser?.role}</span>
              </div>
              {['Profile', 'Settings', 'API Keys'].map(item => (
                <button key={item} className="w-full text-left px-4 py-2.5 text-xs text-gray-600 dark:text-white/60 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-white/[0.05] transition-all">
                  {item}
                </button>
              ))}
              <button onClick={() => { logout(); router.push('/login') }}
                className="w-full text-left px-4 py-2.5 text-xs text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-all border-t border-gray-100 dark:border-white/[0.06]">
                Sign Out
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </header>
  )
}
