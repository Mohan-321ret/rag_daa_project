'use client'
import { useCallback, useEffect, useState } from 'react'
import { UserCog, Search, Users, Globe2, Loader2, Plus, Trash2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission, ROLE_LABELS, type Role } from '@/lib/rbac'
import { usersApi, domainsApi, type UserOut, type DomainOut, ApiError } from '@/lib/api'

const ROLE_BADGE: Record<string, string> = {
  platform_owner: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/15 dark:text-violet-400 dark:border-violet-500/25',
  super_admin: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/15 dark:text-blue-400 dark:border-blue-500/25',
  domain_manager: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-500/15 dark:text-cyan-400 dark:border-cyan-500/25',
  hr: 'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-500/15 dark:text-teal-400 dark:border-teal-500/25',
  analyst: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/25',
  standard_employee: 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-white/[0.06] dark:text-white/60 dark:border-white/[0.1]',
  client_user: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/15 dark:text-amber-400 dark:border-amber-500/25',
  guest_user: 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-500/15 dark:text-gray-400 dark:border-gray-500/25',
}

export default function DomainAssignmentsPage() {
  const [users, setUsers] = useState<UserOut[]>([])
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [domainFilter, setDomainFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [us, ds] = await Promise.all([
        usersApi.list({ limit: 200 }),
        domainsApi.list(),
      ])
      setUsers(us.users)
      setDomains(ds.domains)
    } catch {}
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const domainMap = Object.fromEntries(domains.map(d => [d.id, d.name]))

  const filtered = users.filter(u => {
    const matchSearch = !search ||
      u.full_name?.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase())
    const matchDomain = !domainFilter ||
      (u.domains ?? []).some((d: any) => d.id === domainFilter || d === domainFilter)
    return matchSearch && matchDomain
  })

  return (
    <PermissionGate permission={Permission.DOMAIN_ASSIGN}>
      <AdminSectionShell
        title="Domain Assignments"
        description="View and manage which users belong to which domains."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Domain Assignments' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-cyan-50 text-cyan-700 border border-cyan-200 dark:bg-cyan-500/15 dark:text-cyan-300 dark:border-cyan-500/20">{users.length} users</span>}
      >
        {/* Filters */}
        <div className="flex gap-3 mb-5">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-white/30" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search users…"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/25 rounded-xl pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 transition-all"
            />
          </div>
          <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)}
            className="bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500 min-w-40"
          >
            <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All Domains</option>
            {domains.map(d => <option key={d.id} value={d.id} className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">{d.name}</option>)}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-adaptive-secondary">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading…</span>
          </div>
        ) : (
          <div className="bg-white dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl overflow-hidden shadow-sm dark:shadow-none">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 dark:border-white/[0.06]">
                  <th className="text-left px-4 py-3 text-gray-500 dark:text-white/35 font-medium">User</th>
                  <th className="text-left px-4 py-3 text-gray-500 dark:text-white/35 font-medium">Role</th>
                  <th className="text-left px-4 py-3 text-gray-500 dark:text-white/35 font-medium">Assigned Domains</th>
                  <th className="text-right px-4 py-3 text-gray-500 dark:text-white/35 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u, i) => (
                  <tr key={u.id} className="border-b border-gray-100 dark:border-white/[0.04] hover:bg-gray-50 dark:hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3">
                      <div>
                        <p className="text-gray-900 dark:text-white/80 font-medium">{u.full_name || '—'}</p>
                        <p className="text-gray-500 dark:text-white/35">{u.email}</p>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${ROLE_BADGE[u.role] ?? ROLE_BADGE.guest_user}`}>
                        {ROLE_LABELS[u.role as Role] ?? u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {(u.domains ?? []).length === 0 ? (
                          <span className="text-gray-400 dark:text-white/25">No domains</span>
                        ) : (u.domains ?? []).map((d: any) => (
                          <span key={d.id ?? d} className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/20 text-[10px]">
                            {domainMap[d.id ?? d] ?? d.name ?? d}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                        u.is_active !== false
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/20'
                          : 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/15 dark:text-red-400 dark:border-red-500/20'
                      }`}>
                        {u.is_active !== false ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="py-10 text-center text-sm text-adaptive-muted">No users match your filters</div>
            )}
          </div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
