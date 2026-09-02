'use client'
import { useCallback, useEffect, useState } from 'react'
import { Globe2, Plus, Pencil, Power, Loader2, Search, Building2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { AdminSectionShell } from '@/components/admin/AdminSectionShell'
import { PermissionGate } from '@/components/admin/PermissionGate'
import { Permission } from '@/lib/rbac'
import { domainsApi, type DomainOut, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Modal, Btn, EmptyState } from '@/components/shared/index'

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${
      active ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20'
              : 'bg-red-500/15 text-red-400 border-red-500/20'
    }`}>
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}

export default function DomainsPage() {
  const [domains, setDomains] = useState<DomainOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [editDomain, setEditDomain] = useState<DomainOut | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ name: '', description: '' })

  const load = useCallback(async () => {
    try {
      setLoading(true); setError(null)
      const res = await domainsApi.list()
      setDomains(res.domains)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load domains')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () => { setForm({ name: '', description: '' }); setCreateOpen(true) }
  const openEdit = (d: DomainOut) => { setForm({ name: d.name, description: d.description ?? '' }); setEditDomain(d) }

  const handleSave = async () => {
    setSaving(true)
    try {
      if (editDomain) {
        await domainsApi.update(editDomain.id, form)
        setEditDomain(null)
      } else {
        const key = form.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
        await domainsApi.create({ key, ...form })
        setCreateOpen(false)
      }
      load()
    } catch (e) { /* swallow */ }
    finally { setSaving(false) }
  }

  const handleToggle = async (d: DomainOut) => {
    try {
      await domainsApi.update(d.id, { is_active: !d.is_active })
      load()
    } catch {}
  }

  const filtered = domains.filter(d =>
    !search || d.name.toLowerCase().includes(search.toLowerCase()) ||
    (d.description ?? '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <PermissionGate permission={Permission.DOMAIN_MANAGE}>
      <AdminSectionShell
        title="Domains"
        description="Create and manage organizational domains."
        breadcrumbs={[{ label: 'Admin Panel', href: '/admin/users' }, { label: 'Domains' }]}
        badge={<span className="px-2 py-0.5 rounded-full text-[10px] bg-cyan-500/15 text-cyan-300 border border-cyan-500/20">{domains.length} domains</span>}
        action={
          <Btn onClick={openCreate} size="sm" className="flex items-center gap-1.5">
            <Plus className="w-3.5 h-3.5" /> New Domain
          </Btn>
        }
      >
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search domains..."
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder:text-white/25 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-white/40">
            <Loader2 className="w-5 h-5 animate-spin" /><span className="text-sm">Loading domains…</span>
          </div>
        ) : error ? (
          <div className="py-10 text-center text-sm text-red-400">{error}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={<Building2 className="w-5 h-5" />} title="No domains found" description={search ? 'Try a different search' : 'Create your first domain to get started'} />
        ) : (
          <div className="grid grid-cols-1 gap-3">
            {filtered.map(d => (
              <motion.div key={d.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-4 p-4 bg-white/[0.02] border border-white/[0.06] rounded-xl hover:border-white/10 transition-colors"
              >
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/20 flex items-center justify-center flex-shrink-0">
                  <Globe2 className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-white/85 truncate">{d.name}</p>
                    <StatusBadge active={d.is_active ?? true} />
                  </div>
                  {d.description && <p className="text-xs text-white/40 mt-0.5 truncate">{d.description}</p>}
                  <p className="text-[10px] text-white/25 mt-1">Created {formatDateTime(d.created_at)}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => openEdit(d)} className="p-1.5 rounded-lg hover:bg-white/[0.06] text-white/40 hover:text-white/70 transition-colors">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => handleToggle(d)} className="p-1.5 rounded-lg hover:bg-white/[0.06] text-white/40 hover:text-white/70 transition-colors">
                    <Power className="w-3.5 h-3.5" />
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}

        {/* Create/Edit Modal */}
        <Modal
          open={createOpen || !!editDomain}
          onClose={() => { setCreateOpen(false); setEditDomain(null) }}
          title={editDomain ? 'Edit Domain' : 'New Domain'}
        >
          <div className="space-y-4 p-4">
            <div>
              <label className="block text-xs font-medium text-white/60 mb-1.5">Domain Name</label>
              <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                className="w-full bg-white/[0.05] border border-white/[0.1] rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50"
                placeholder="e.g. Human Resources"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-white/60 mb-1.5">Description</label>
              <textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
                rows={3} className="w-full bg-white/[0.05] border border-white/[0.1] rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50 resize-none"
                placeholder="Optional description…"
              />
            </div>
            <div className="flex gap-2 pt-2">
              <Btn onClick={handleSave} disabled={!form.name.trim() || saving} className="flex-1 flex items-center justify-center gap-1.5">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editDomain ? 'Save Changes' : 'Create Domain'}
              </Btn>
              <Btn variant="ghost" onClick={() => { setCreateOpen(false); setEditDomain(null) }} className="flex-1">Cancel</Btn>
            </div>
          </div>
        </Modal>
      </AdminSectionShell>
    </PermissionGate>
  )
}
