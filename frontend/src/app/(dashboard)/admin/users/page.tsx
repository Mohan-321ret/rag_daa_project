'use client'
import { useCallback, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Search, Plus, Pencil, UserX, UserCheck, ShieldCheck, Loader2,
  Users as UsersIcon, Globe2,
} from 'lucide-react'
import { Can, PageHeader, EmptyState, Modal, ConfirmDialog, Btn } from '@/components/shared/index'
import {
  authApi, usersApi, domainsApi, permissionsApi, ApiError,
  type UserOut, type DomainOut, type UserCreate, type UserUpdate,
} from '@/lib/api'
import { Permission, Role, ROLE_RANK, ROLE_LABELS, canAssignRole } from '@/lib/rbac'
import { usePermission, useRole } from '@/lib/usePermission'
import { formatDateTime } from '@/lib/utils'

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

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${ROLE_BADGE[role] ?? ROLE_BADGE.guest_user}`}>
      {ROLE_LABELS[role as Role] ?? role}
    </span>
  )
}

export default function AdminUsersPage() {
  const [tab, setTab] = useState<'users' | 'domains'>('users')
  const [me, setMe] = useState<UserOut | null>(null)

  useEffect(() => { authApi.me().then(setMe).catch(() => {}) }, [])

  return (
    <div className="space-y-6">
      <PageHeader title="Admin Panel" description="User, domain, and access management" />

      <div className="flex items-center gap-1 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-xl p-1 w-fit">
        {[
          { id: 'users' as const, label: 'Users', icon: UsersIcon },
          { id: 'domains' as const, label: 'Domains', icon: Globe2 },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-600 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70'}`}>
            <t.icon className="w-3.5 h-3.5" /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'users' ? <UsersPanel me={me} /> : <DomainsPanel />}
    </div>
  )
}

// ── Users tab ────────────────────────────────────────────────────────────────

function UsersPanel({ me }: { me: UserOut | null }) {
  const [users, setUsers] = useState<UserOut[]>([])
  const [total, setTotal] = useState(0)
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [domainFilter, setDomainFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<UserOut | null>(null)
  const [confirmTarget, setConfirmTarget] = useState<UserOut | null>(null)
  const [permissionsUser, setPermissionsUser] = useState<UserOut | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [userRes, domainRes] = await Promise.all([
        usersApi.list({
          q: q || undefined, role: roleFilter || undefined, domain_id: domainFilter || undefined,
          status: (statusFilter as 'active' | 'inactive') || undefined, limit: 100,
        }),
        domainsApi.list(),
      ])
      setUsers(userRes.users)
      setTotal(userRes.total)
      setDomains(domainRes.domains)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load users.')
    } finally {
      setLoading(false)
    }
  }, [q, roleFilter, domainFilter, statusFilter])

  useEffect(() => { load() }, [load])

  const deactivate = async () => {
    if (!confirmTarget) return
    setSaving(true)
    try {
      await usersApi.update(confirmTarget.id, { is_active: !confirmTarget.is_active })
      setConfirmTarget(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update status.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] rounded-xl px-3 py-2 flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-gray-400 dark:text-white/30" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name or email..."
            className="bg-transparent text-xs text-gray-900 dark:text-white/70 placeholder:text-gray-400 dark:placeholder:text-white/25 outline-none flex-1" />
        </div>
        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
          className="bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500">
          <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All roles</option>
          {Object.values(Role).map(r => <option key={r} value={r} className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">{ROLE_LABELS[r]}</option>)}
        </select>
        <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)}
          className="bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500">
          <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">All domains</option>
          {domains.map(d => <option key={d.id} value={d.id} className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">{d.name}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white rounded-xl px-3 py-2 text-xs outline-none focus:border-blue-500">
          <option value="" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Any status</option>
          <option value="active" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Active</option>
          <option value="inactive" className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">Inactive</option>
        </select>
        <span className="text-[11px] text-gray-400 dark:text-white/30 ml-auto">{total} user{total === 1 ? '' : 's'}</span>
        <Can permission={Permission.USER_CREATE}>
          <Btn size="sm" onClick={() => setCreateOpen(true)}><Plus className="w-3.5 h-3.5" /> Create User</Btn>
        </Can>
      </div>

      {error && <div className="px-3 py-2.5 rounded-xl bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 text-xs text-red-600 dark:text-red-400">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-5 h-5 text-gray-400 dark:text-white/30 animate-spin" /></div>
      ) : users.length === 0 ? (
        <EmptyState icon={<UsersIcon className="w-5 h-5" />} title="No users found" description="Try a different filter, or create the first one." />
      ) : (
        <div className="bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl overflow-hidden overflow-x-auto shadow-sm dark:shadow-none">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-200 dark:border-white/[0.06]">
                {['Name', 'Role', 'Status', 'Domains', 'Department', 'Last Login', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-[11px] font-semibold text-gray-500 dark:text-white/40 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u, i) => (
                <motion.tr key={u.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i * 0.02, 0.3) }}
                  className="border-b border-gray-100 dark:border-white/[0.04] last:border-0 hover:bg-gray-50 dark:hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <p className="text-xs font-medium text-gray-900 dark:text-white/80">{u.full_name || u.email.split('@')[0]}</p>
                    <p className="text-[11px] text-gray-500 dark:text-white/35">{u.email}</p>
                  </td>
                  <td className="px-4 py-3"><RoleBadge role={u.role} /></td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${u.status === 'active' ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/25' : 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-500/15 dark:text-gray-400 dark:border-gray-500/25'}`}>
                      {u.status === 'active' ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1 max-w-[180px]">
                      {u.domains.length === 0
                        ? <span className="text-[11px] text-gray-400 dark:text-white/25">—</span>
                        : u.domains.map(d => <span key={d.id} className="text-[10px] bg-gray-100 text-gray-700 dark:bg-white/[0.06] dark:text-white/50 px-1.5 py-0.5 rounded-full">{d.name}</span>)}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 dark:text-white/50">{u.department || '—'}</td>
                  <td className="px-4 py-3 text-[11px] text-gray-500 dark:text-white/40">{u.last_login ? formatDateTime(u.last_login) : 'Never'}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button title="View permissions" onClick={() => setPermissionsUser(u)}
                        className="p-1.5 rounded-lg text-gray-400 dark:text-white/30 hover:text-gray-700 dark:hover:text-white/70 hover:bg-gray-100 dark:hover:bg-white/[0.06] transition-colors">
                        <ShieldCheck className="w-3.5 h-3.5" />
                      </button>
                      <Can permission={[Permission.USER_UPDATE, Permission.ROLE_ASSIGN, Permission.DOMAIN_ASSIGN]} any>
                        <button title="Edit" onClick={() => setEditingUser(u)}
                          className="p-1.5 rounded-lg text-gray-400 dark:text-white/30 hover:text-gray-700 dark:hover:text-white/70 hover:bg-gray-100 dark:hover:bg-white/[0.06] transition-colors">
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                      </Can>
                      <Can permission={Permission.USER_DEACTIVATE}>
                        <button title={u.status === 'active' ? 'Deactivate' : 'Reactivate'} onClick={() => setConfirmTarget(u)}
                          className="p-1.5 rounded-lg text-gray-400 dark:text-white/30 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors">
                          {u.status === 'active' ? <UserX className="w-3.5 h-3.5" /> : <UserCheck className="w-3.5 h-3.5" />}
                        </button>
                      </Can>
                    </div>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <UserFormModal
        open={createOpen} onClose={() => setCreateOpen(false)} onSaved={load}
        mode="create" me={me} domains={domains}
      />
      <UserFormModal
        open={!!editingUser} onClose={() => setEditingUser(null)} onSaved={load}
        mode="edit" me={me} domains={domains} user={editingUser}
      />
      <ConfirmDialog
        open={!!confirmTarget} onClose={() => setConfirmTarget(null)} onConfirm={deactivate} loading={saving}
        title={confirmTarget?.status === 'active' ? 'Deactivate user?' : 'Reactivate user?'}
        description={
          confirmTarget?.status === 'active'
            ? `${confirmTarget?.full_name || confirmTarget?.email} will immediately lose access to the platform. This can be undone by reactivating the account.`
            : `${confirmTarget?.full_name || confirmTarget?.email} will regain access to the platform.`
        }
        confirmLabel={confirmTarget?.status === 'active' ? 'Deactivate' : 'Reactivate'}
        danger={confirmTarget?.status === 'active'}
      />
      <PermissionsViewerModal user={permissionsUser} onClose={() => setPermissionsUser(null)} />
    </div>
  )
}

// ── Create / edit user modal ────────────────────────────────────────────────

function UserFormModal({
  open, onClose, onSaved, mode, me, domains, user,
}: {
  open: boolean; onClose: () => void; onSaved: () => void
  mode: 'create' | 'edit'; me: UserOut | null; domains: DomainOut[]; user?: UserOut | null
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [department, setDepartment] = useState('')
  const [role, setRole] = useState<string>(Role.GUEST_USER)
  const [domainIds, setDomainIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const canEditRole = usePermission(Permission.ROLE_ASSIGN)
  const canEditDomains = usePermission(Permission.DOMAIN_ASSIGN)
  const canEditProfile = usePermission(Permission.USER_UPDATE)

  useEffect(() => {
    if (!open) return
    setError(null)
    setPassword('')
    if (mode === 'edit' && user) {
      setEmail(user.email)
      setFullName(user.full_name || '')
      setDepartment(user.department || '')
      setRole(user.role)
      setDomainIds(user.domains.map(d => d.id))
    } else {
      setEmail(''); setFullName(''); setDepartment(''); setRole(Role.GUEST_USER); setDomainIds([])
    }
  }, [open, mode, user])

  const isUnrestricted = me ? ROLE_RANK[me.role as Role] >= ROLE_RANK[Role.SUPER_ADMIN] : false
  const myDomainIds = new Set((me?.domains ?? []).map(d => d.id))
  const selectableDomains = isUnrestricted ? domains : domains.filter(d => myDomainIds.has(d.id))
  const selectableRoles = me ? Object.values(Role).filter(r => canAssignRole(me.role, r)) : []

  const toggleDomain = (id: string) => {
    setDomainIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      if (mode === 'create') {
        const body: UserCreate = { email, password, full_name: fullName || undefined, department: department || undefined, role, domain_ids: domainIds }
        await usersApi.create(body)
      } else if (user) {
        const body: UserUpdate = {}
        if (canEditProfile) { body.full_name = fullName; body.department = department }
        if (canEditRole && role !== user.role) body.role = role
        if (canEditDomains) body.domain_ids = domainIds
        await usersApi.update(user.id, body)
      }
      onClose()
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save user.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={mode === 'create' ? 'Create User' : `Edit ${user?.full_name || user?.email || 'User'}`} maxWidth="max-w-lg">
      <div className="space-y-4">
        {error && <div className="px-3 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">{error}</div>}

        {mode === 'create' && (
          <div>
            <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Email</label>
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" placeholder="name@company.com"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
        )}
        {mode === 'create' && (
          <div>
            <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Initial password</label>
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="At least 8 characters"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
        )}

        <fieldset disabled={!canEditProfile && mode === 'edit'} className="grid grid-cols-2 gap-3 disabled:opacity-50">
          <div>
            <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Full name</label>
            <input value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Doe"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Department</label>
            <input value={department} onChange={e => setDepartment(e.target.value)} placeholder="e.g. Payroll"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
        </fieldset>

        <div>
          <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Role</label>
          <select value={role} onChange={e => setRole(e.target.value)} disabled={!canEditRole}
            className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-50">
            {selectableRoles.map(r => <option key={r} value={r} className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">{ROLE_LABELS[r]}</option>)}
            {mode === 'edit' && user && !selectableRoles.includes(user.role as Role) && (
              <option value={user.role} className="bg-white text-gray-900 dark:bg-slate-900 dark:text-white">{ROLE_LABELS[user.role as Role] ?? user.role} (current)</option>
            )}
          </select>
          {!canEditRole && <p className="text-[11px] text-adaptive-muted mt-1">You don&apos;t have permission to change roles.</p>}
        </div>

        <div>
          <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Domains</label>
          <div className="flex flex-wrap gap-1.5 p-2.5 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-white/[0.06] rounded-xl min-h-[44px]">
            {selectableDomains.length === 0 && <span className="text-[11px] text-adaptive-muted">No domains available to assign.</span>}
            {selectableDomains.map(d => (
              <button key={d.id} type="button" disabled={!canEditDomains} onClick={() => toggleDomain(d.id)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all disabled:opacity-50 disabled:cursor-not-allowed ${domainIds.includes(d.id) ? 'bg-blue-600 border-blue-500 text-white' : 'bg-white dark:bg-white/[0.04] border-gray-200 dark:border-white/[0.08] text-gray-600 dark:text-white/50 hover:text-gray-900 dark:hover:text-white/80'}`}>
                {d.name}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Btn variant="ghost" size="sm" onClick={onClose} disabled={saving}>Cancel</Btn>
          <Btn size="sm" onClick={submit} disabled={saving || (mode === 'create' && (!email || password.length < 8))}>
            {saving ? 'Saving…' : mode === 'create' ? 'Create User' : 'Save Changes'}
          </Btn>
        </div>
      </div>
    </Modal>
  )
}

// ── Permissions viewer (read-only) ──────────────────────────────────────────

function PermissionsViewerModal({ user, onClose }: { user: UserOut | null; onClose: () => void }) {
  const [loading, setLoading] = useState(false);
  const [perms, setPerms] = useState<string[]>([])

  useEffect(() => {
    if (!user) return
    setLoading(true)
    permissionsApi.matrix()
      .then(m => setPerms(m.roles.find(r => r.key === user.role)?.permissions ?? []))
      .catch(() => setPerms([]))
      .finally(() => setLoading(false))
  }, [user])

  return (
    <Modal open={!!user} onClose={onClose} title={`Permissions — ${user ? (ROLE_LABELS[user.role as Role] ?? user.role) : ''}`} maxWidth="max-w-md">
      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="w-4 h-4 text-white/30 animate-spin" /></div>
      ) : perms.length === 0 ? (
        <p className="text-xs text-white/30">This role holds no permissions, or you don&apos;t have access to view the matrix.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5 max-h-80 overflow-y-auto">
          {perms.sort().map(p => (
            <span key={p} className="text-[11px] font-mono bg-white/[0.05] text-white/60 px-2 py-1 rounded-lg">{p}</span>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ── Domains tab ──────────────────────────────────────────────────────────────

function DomainsPanel() {
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<DomainOut | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await domainsApi.list(true)
      setDomains(res.domains)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load domains.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-white/40">{domains.length} domain{domains.length === 1 ? '' : 's'}</p>
        <Can permission={Permission.DOMAIN_MANAGE}>
          <Btn size="sm" onClick={() => { setEditing(null); setFormOpen(true) }}><Plus className="w-3.5 h-3.5" /> Create Domain</Btn>
        </Can>
      </div>

      {error && <div className="px-3 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="w-5 h-5 text-gray-400 dark:text-white/30 animate-spin" /></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {domains.map(d => (
            <motion.div key={d.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className="bg-white dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.07] rounded-2xl p-4 shadow-sm dark:shadow-none">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white/85">{d.name}</p>
                  <p className="text-[11px] font-mono text-gray-400 dark:text-white/30">{d.key}</p>
                </div>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${d.is_active ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/25' : 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-500/15 dark:text-gray-400 dark:border-gray-500/25'}`}>
                  {d.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
              <p className="text-xs text-gray-500 dark:text-white/40 mb-3 min-h-[2rem]">{d.description || 'No description.'}</p>
              <Can permission={Permission.DOMAIN_MANAGE}>
                <button onClick={() => { setEditing(d); setFormOpen(true) }}
                  className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline transition-colors">Edit</button>
              </Can>
            </motion.div>
          ))}
        </div>
      )}

      <DomainFormModal open={formOpen} onClose={() => setFormOpen(false)} onSaved={load} domain={editing} />
    </div>
  )
}

function DomainFormModal({ open, onClose, onSaved, domain }: { open: boolean; onClose: () => void; onSaved: () => void; domain: DomainOut | null }) {
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setError(null)
    setKey(domain?.key || '')
    setName(domain?.name || '')
    setDescription(domain?.description || '')
    setIsActive(domain?.is_active ?? true)
  }, [open, domain])

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      if (domain) {
        await domainsApi.update(domain.id, { name, description: description || undefined, is_active: isActive })
      } else {
        await domainsApi.create({ key, name, description: description || undefined })
      }
      onClose()
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save domain.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={domain ? `Edit ${domain.name}` : 'Create Domain'} maxWidth="max-w-sm">
      <div className="space-y-4">
        {error && <div className="px-3 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">{error}</div>}
        {!domain && (
          <div>
            <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Key (URL-safe, permanent)</label>
            <input value={key} onChange={e => setKey(e.target.value.toLowerCase())} placeholder="e.g. customer-support"
              className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
        )}
        <div>
          <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Name</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Customer Support"
            className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500" />
        </div>
        <div>
          <label className="text-xs font-medium text-adaptive-secondary mb-1.5 block">Description</label>
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2}
            className="w-full bg-gray-50 dark:bg-white/[0.04] border border-gray-200 dark:border-white/[0.08] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-white/20 rounded-xl px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none" />
        </div>
        {domain && (
          <label className="flex items-center gap-2 text-xs text-adaptive-secondary cursor-pointer">
            <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)} className="accent-blue-600" />
            Active
          </label>
        )}
        <div className="flex items-center justify-end gap-2 pt-2">
          <Btn variant="ghost" size="sm" onClick={onClose} disabled={saving}>Cancel</Btn>
          <Btn size="sm" onClick={submit} disabled={saving || !name || (!domain && !key)}>
            {saving ? 'Saving…' : domain ? 'Save Changes' : 'Create Domain'}
          </Btn>
        </div>
      </div>
    </Modal>
  )
}
