import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { clearToken } from '@/lib/api'

interface AppState {
  sidebarCollapsed: boolean
  setSidebarCollapsed: (v: boolean) => void
  toggleSidebar: () => void
  activeWorkspace: string
  setActiveWorkspace: (w: string) => void
  notifications: Notification[]
  addNotification: (n: Notification) => void
  clearNotifications: () => void
  isAuthenticated: boolean
  setAuthenticated: (v: boolean) => void
  // `role` is the RBAC role string from the backend (see lib/rbac.ts's Role
  // union) — never hardcode/assume a role here, it drives real authorization.
  currentUser: { name: string; email: string; role: string } | null
  setCurrentUser: (u: AppState['currentUser']) => void
  logout: () => void
}

interface Notification {
  id: string
  title: string
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
  timestamp: string
  read: boolean
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      activeWorkspace: 'Enterprise HQ',
      setActiveWorkspace: (w) => set({ activeWorkspace: w }),
      notifications: [
        { id: 'n1', title: 'Processing Complete', message: 'Q4 Financial Report has been processed successfully', type: 'success', timestamp: new Date().toISOString(), read: false },
        { id: 'n2', title: 'Knowledge Update', message: 'Version 8 of knowledge base is now active', type: 'info', timestamp: new Date(Date.now() - 300000).toISOString(), read: false },
        { id: 'n3', title: 'High Hallucination Rate', message: 'Query confidence dropped below threshold', type: 'warning', timestamp: new Date(Date.now() - 600000).toISOString(), read: false },
        { id: 'n4', title: 'Failed Upload', message: 'Vendor Contracts 2024.pdf failed to process', type: 'error', timestamp: new Date(Date.now() - 900000).toISOString(), read: true },
      ],
      addNotification: (n) => set((s) => ({ notifications: [n, ...s.notifications] })),
      clearNotifications: () => set((s) => ({ notifications: s.notifications.map(n => ({ ...n, read: true })) })),
      isAuthenticated: false,
      setAuthenticated: (v) => set({ isAuthenticated: v }),
      currentUser: null,
      setCurrentUser: (u) => set({ currentUser: u }),
      logout: () => { clearToken(); set({ isAuthenticated: false, currentUser: null }) },
    }),
    { name: 'daa-rag-store', partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, activeWorkspace: s.activeWorkspace, isAuthenticated: s.isAuthenticated, currentUser: s.currentUser }) }
  )
)
