'use client'
import { useCallback, useEffect, useState } from 'react'
import { UserCog, Search, Users, Globe2, Loader2, Plus, Trash2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission, ROLE_LABELS, type Role } from '@/lib/rbac'
import { usersApi, domainsApi, type UserOut, type DomainOut, ApiError } from '@/lib/api'

const ROLE_BADGE: Record<string, string> = {
  platform_owner: 'bg-violet-500/15 text-violet-400 border-violet-500/25',
  super_admin: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  domain_manager: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  analyst: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  standard_employee: 'bg-white/[0.06] text-white/60 border-white/[0.1]',
  client_user: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  guest_user: 'bg-gray-500/15 text-gray-400 border-gray-500/25',
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
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-cyan-500/15 text-cyan-300 border border-cyan-500/20">{users.length} users</span>}
      >
        {/* Filters */}
        <div className="flex gap-3 mb-5">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search users…"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-blue-500/50"
            />
          </div>
          <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)}
            className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-sm text-white/70 focus:outline-none focus:border-blue-500/50 min-w-40"
          >
            <option value="">All Domains</option>
            {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading…</span>
          </div>
        ) : (
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="text-left px-4 py-3 text-white/35 font-medium">User</th>
                  <th className="text-left px-4 py-3 text-white/35 font-medium">Role</th>
                  <th className="text-left px-4 py-3 text-white/35 font-medium">Assigned Domains</th>
                  <th className="text-right px-4 py-3 text-white/35 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u, i) => (
                  <tr key={u.id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3">
                      <div>
                        <p className="text-white/80 font-medium">{u.full_name || '—'}</p>
                        <p className="text-white/35">{u.email}</p>
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
                          <span className="text-white/25">No domains</span>
                        ) : (u.domains ?? []).map((d: any) => (
                          <span key={d.id ?? d} className="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-500/20 text-[10px]">
                            {domainMap[d.id ?? d] ?? d.name ?? d}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                        u.is_active !== false
                          ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20'
                          : 'bg-red-500/15 text-red-400 border-red-500/20'
                      }`}>
                        {u.is_active !== false ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="py-10 text-center text-sm text-white/30">No users match your filters</div>
            )}
          </div>
        )}
      </AdminSectionShell>
    </PermissionGate>
  )
}
