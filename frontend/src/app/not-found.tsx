'use client'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { Brain, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#080810] flex items-center justify-center">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="text-center">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center mx-auto mb-6">
          <Brain className="w-8 h-8 text-white" />
        </div>
        <h1 className="text-6xl font-bold text-white mb-2">404</h1>
        <p className="text-white/50 mb-8">This page doesn&apos;t exist in the knowledge base</p>
        <Link href="/dashboard" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-sm font-semibold text-white transition-all">
          <ArrowLeft className="w-4 h-4" /> Back to Dashboard
        </Link>
      </motion.div>
    </div>
  )
}
