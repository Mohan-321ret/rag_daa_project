'use client'
/**
 * AdminLayout — Inner layout for all /admin/* pages.
 * Renders the AdminSidebar beside the page content.
 * Placed at src/app/(dashboard)/admin/layout.tsx.
 */
import { AdminSidebar } from '@/components/admin/AdminSidebar'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full min-h-0">
      <AdminSidebar />
      <div className="flex-1 overflow-y-auto min-w-0 p-6">
        {children}
      </div>
    </div>
  )
}
