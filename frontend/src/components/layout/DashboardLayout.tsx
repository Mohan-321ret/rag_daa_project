'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { Navbar } from './Navbar'
import { motion } from 'framer-motion'
import { getToken } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const setAuthenticated = useAppStore(s => s.setAuthenticated)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      setAuthenticated(false)
      router.replace('/login')
    } else {
      setChecked(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!checked) return null

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-[#080810] overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <Navbar />
        <motion.main
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="flex-1 overflow-y-auto p-6"
        >
          {children}
        </motion.main>
      </div>
    </div>
  )
}
