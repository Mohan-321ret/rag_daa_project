'use client'
import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import {
  Cpu, Star, CheckCircle, XCircle, Loader2, Plug, Pencil, Plus, KeyRound, Settings2, Zap, Activity,
} from 'lucide-react'
import { Can, PageHeader, Card, StatusBadge, Modal, Btn, EmptyState } from '@/components/shared/index'
import { DataTable } from '@/components/shared/DataTable'
import {
  llmConfigApi, ApiError,
  type LLMProviderConfigOut, type LLMProviderCreate, type LLMProviderUpdate,
} from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { Permission } from '@/lib/rbac'

type ProviderRow = LLMProviderConfigOut & { id: string }

type Tab = 'providers' | 'models' | 'active' | 'config' | 'test'

const emptyForm: LLMProviderCreate = {
  name: '', provider: '', model: '', endpoint: '', api_key_env_var: '',
  temperature: 0.7, max_tokens: undefined, context_window: undefined,
}

export default function LLMManagementPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab') as Tab | null

  const [tab, setTab] = useState<Tab>('providers')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ProviderRow | null>(null)
  const [form, setForm] = useState<LLMProviderCreate>(emptyForm)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string; latencyMs: number | null } | null>(null)
  const queryClient = useQueryClient()

  const { data: registry } = useQuery({ queryKey: ['llm-registry'], queryFn: () => llmConfigApi.registry() })
  const { data, isLoading, isError, error, refetch } = useQuery({ queryKey: ['llm-providers'], queryFn: () => llmConfigApi.list() })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['llm-providers'] })

  // Sync tab state with query params
  useEffect(() => {
    if (tabParam) {
      setTab(tabParam)
    } else {
      setTab('providers')
    }
  }, [tabParam])

  const openCreate = () => { setEditing(null); setForm(emptyForm); setFormError(null); setFormOpen(true) }
  const openEdit = (row: ProviderRow) => {
    setEditing(row)
    setForm({
      name: row.name, provider: row.provider, model: row.model,
      endpoint: row.endpoint ?? '', api_key_env_var: row.api_key_env_var ?? '',
      temperature: row.temperature, max_tokens: row.max_tokens ?? undefined, context_window: row.context_window ?? undefined,
    })
    setFormError(null)
    setFormOpen(true)
  }

  const submitForm = async () => {
    setSaving(true)
    setFormError(null)
    try {
      const payload = {
        ...form,
        endpoint: form.endpoint || undefined,
        api_key_env_var: form.api_key_env_var || undefined,
        max_tokens: form.max_tokens || undefined,
        context_window: form.context_window || undefined,
      }
      if (editing) {
        const { provider: _provider, ...updatable } = payload
        await llmConfigApi.update(editing.id, updatable as LLMProviderUpdate)
      } else {
        await llmConfigApi.create(payload)
      }
      setFormOpen(false)
      refresh()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const runAction = async (id: string, key: string, fn: () => Promise<unknown>) => {
    setBusyId(`${key}-${id}`)
    setActionError(null)
    try {
      await fn()
      refresh()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Action failed')
    } finally {
      setBusyId(null)
    }
  }

  const runTest = async (id: string) => {
    setBusyId(`test-${id}`)
    setTestResult(null)
    try {
      const res = await llmConfigApi.testConnection(id)
      setTestResult({ id, success: res.success, message: res.message, latencyMs: res.latency_ms })
    } catch (err) {
      setTestResult({ id, success: false, message: err instanceof ApiError ? err.message : 'Test failed', latencyMs: null })
    } finally {
      setBusyId(null)
    }
  }

  const selectTab = (t: Tab) => {
    router.push(`/admin/llm?tab=${t}`)
  }

  const rawRows: ProviderRow[] = (data?.providers ?? []).map(p => ({ ...p, id: p.id }))

  // Filter based on active tab
  let displayedRows = rawRows
  if (tab === 'active') {
    displayedRows = rawRows.filter(p => p.is_current)
  }

  const activeConfig = rawRows.find(p => p.is_current)

  const columns = [
    { key: 'name', label: 'Config', render: (_: unknown, row: ProviderRow) => (
      <div className="flex items-center gap-2">
        {row.is_current && <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400 flex-shrink-0" />}
        <div>
          <p className="text-xs font-medium text-white/80">{row.name}</p>
          <p className="text-[10px] text-white/30">{row.provider} · {row.model}</p>
        </div>
      </div>
    )},
    { key: 'endpoint', label: 'Endpoint', render: (v: unknown) => <span className="text-[11px] font-mono text-white/40">{v ? String(v) : '—'}</span> },
    { key: 'api_key_env_var', label: 'API Key', render: (_: unknown, row: ProviderRow) => (
      row.api_key_env_var ? (
        <span className="flex items-center gap-1.5 text-[11px] font-mono text-white/50">
          <KeyRound className="w-3 h-3" /> {row.api_key_env_var}
          {row.api_key_configured
            ? <span title="Configured"><CheckCircle className="w-3 h-3 text-emerald-400" /></span>
            : <span title="Not set on this server"><XCircle className="w-3 h-3 text-red-400" /></span>}
        </span>
      ) : <span className="text-[11px] text-white/25">Not required</span>
    )},
    { key: 'temperature', label: 'Temp', render: (v: unknown) => <span className="text-xs text-white/60">{Number(v).toFixed(2)}</span> },
    { key: 'max_tokens', label: 'Max Tokens', render: (v: unknown) => <span className="text-xs text-white/60">{v ? String(v) : '—'}</span> },
    { key: 'context_window', label: 'Context', render: (v: unknown) => <span className="text-xs text-white/60">{v ? String(v) : '—'}</span> },
    { key: 'status', label: 'Status', render: (v: unknown) => <StatusBadge status={String(v)} /> },
    { key: 'actions', label: '', render: (_: unknown, row: ProviderRow) => (
      <div className="flex items-center justify-end gap-1.5" onClick={e => e.stopPropagation()}>
        <button onClick={() => openEdit(row)} title="Configure" className="p-1.5 rounded-lg text-white/30 hover:text-white/70 hover:bg-white/[0.06] transition-colors">
          <Pencil className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => runTest(row.id)}
          disabled={busyId === `test-${row.id}`}
          title="Test connection"
          className="p-1.5 rounded-lg text-blue-400/70 hover:text-blue-400 hover:bg-blue-500/10 disabled:opacity-30 transition-colors"
        >
          {busyId === `test-${row.id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plug className="w-3.5 h-3.5" />}
        </button>
        {row.status === 'inactive' ? (
          <button
            onClick={() => runAction(row.id, 'activate', () => llmConfigApi.activate(row.id))}
            disabled={busyId === `activate-${row.id}`}
            title="Activate" className="p-1.5 rounded-lg text-emerald-400/70 hover:text-emerald-400 hover:bg-emerald-500/10 disabled:opacity-30 transition-colors"
          >
            {busyId === `activate-${row.id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
          </button>
        ) : (
          <button
            onClick={() => runAction(row.id, 'deactivate', () => llmConfigApi.deactivate(row.id))}
            disabled={busyId === `deactivate-${row.id}` || row.is_current}
            title={row.is_current ? 'Switch active model elsewhere first' : 'Deactivate'}
            className="p-1.5 rounded-lg text-red-400/70 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            {busyId === `deactivate-${row.id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
          </button>
        )}
        {!row.is_current && (
          <Btn variant="secondary" size="sm" disabled={row.status !== 'active' || busyId === `switch-${row.id}`}
            onClick={() => runAction(row.id, 'switch', () => llmConfigApi.switchActive(row.id))}>
            {busyId === `switch-${row.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Star className="w-3 h-3" />} Set Active
          </Btn>
        )}
      </div>
    )},
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="LLM Management" description="Configure LLM providers, active models, and pipeline endpoints">
        <Can permission={Permission.LLM_CONFIGURE}>
          <Btn variant="primary" size="sm" onClick={openCreate}><Plus className="w-3.5 h-3.5" /> Add Provider</Btn>
        </Can>
      </PageHeader>

      <Can
        permission={Permission.LLM_VIEW}
        fallback={<EmptyState icon={<Cpu className="w-5 h-5" />} title="Your role cannot view LLM configuration" description="Ask a Platform Owner or Super Admin for access." />}
      >
        <div className="space-y-6">
          {actionError && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{actionError}</div>
          )}
          {testResult && (
            <div className={`text-xs rounded-xl px-3 py-2 border ${testResult.success ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-red-400 bg-red-500/10 border-red-500/20'}`}>
              {testResult.success ? '✓ Connection success!' : '✗ Connection failed:'} {testResult.message}{testResult.latencyMs != null && ` (${Math.round(testResult.latencyMs)}ms)`}
            </div>
          )}

          {/* Sub-tabs Navigation */}
          <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 w-fit mb-2 flex-wrap">
            {[
              { id: 'providers' as Tab, label: 'Providers', icon: Plug },
              { id: 'models' as Tab, label: 'Models Catalog', icon: Cpu },
              { id: 'active' as Tab, label: 'Active Model', icon: Star },
              { id: 'config' as Tab, label: 'Configuration', icon: Settings2 },
              { id: 'test' as Tab, label: 'Connection Test', icon: Activity },
            ].map(t => {
              const Icon = t.icon
              return (
                <button key={t.id} onClick={() => selectTab(t.id)}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                  <Icon className="w-3.5 h-3.5" />{t.label}
                </button>
              )
            })}
          </div>

          {/* Tab contents */}
          {tab === 'config' ? (
            <Card>
              <h3 className="text-sm font-semibold text-white/70 mb-4 flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-violet-400" /> Active RAG Configuration Parameters
              </h3>
              {activeConfig ? (
                <div className="space-y-4 max-w-md">
                  <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4 space-y-3">
                    <div className="flex justify-between">
                      <span className="text-xs text-white/40">Active Configuration:</span>
                      <span className="text-xs text-white/80 font-bold">{activeConfig.name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-white/40">Active Model:</span>
                      <span className="text-xs text-white/80 font-mono">{activeConfig.model} ({activeConfig.provider})</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-white/40">Temperature:</span>
                      <span className="text-xs text-white/80 font-mono">{activeConfig.temperature.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-white/40">Max Generation Tokens:</span>
                      <span className="text-xs text-white/80 font-mono">{activeConfig.max_tokens ?? 'Unlimited'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-xs text-white/40">Context Window Size:</span>
                      <span className="text-xs text-white/80 font-mono">{activeConfig.context_window ?? 'Default'}</span>
                    </div>
                  </div>
                  <Btn variant="primary" size="sm" onClick={() => openEdit(activeConfig)}>
                    <Pencil className="w-3 h-3" /> Edit Active Configuration
                  </Btn>
                </div>
              ) : (
                <p className="text-xs text-white/35">No current configuration set active. Go to Providers to activate a model.</p>
              )}
            </Card>
          ) : tab === 'test' ? (
            <Card>
              <h3 className="text-sm font-semibold text-white/70 mb-4 flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" /> Model Connectivity Testing Panel
              </h3>
              <p className="text-xs text-white/40 mb-4">Validate credentials and network latency for registered model providers.</p>
              <div className="space-y-3">
                {rawRows.map(row => (
                  <div key={row.id} className="flex items-center justify-between bg-white/[0.02] border border-white/[0.06] rounded-xl p-3">
                    <div>
                      <p className="text-xs font-medium text-white/80">{row.name}</p>
                      <p className="text-[10px] text-white/30">{row.provider} · {row.model} {row.is_current ? '(Active)' : ''}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      {testResult && testResult.id === row.id && (
                        <span className={`text-xs ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
                          {testResult.success ? `Success (${testResult.latencyMs}ms)` : 'Failed'}
                        </span>
                      )}
                      <Btn
                        variant="secondary"
                        size="sm"
                        disabled={busyId === `test-${row.id}`}
                        onClick={() => runTest(row.id)}
                      >
                        {busyId === `test-${row.id}` ? 'Testing...' : 'Test Ping'}
                      </Btn>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ) : (
            <Card>
              <h3 className="text-sm font-semibold text-white/70 mb-4">
                {tab === 'providers' && 'Registered Providers'}
                {tab === 'models' && 'Models Catalog'}
                {tab === 'active' && 'Active Model'}
              </h3>
              {isError ? (
                <div className="text-center py-8 text-sm text-red-400">
                  {error instanceof ApiError ? error.message : 'Failed to load providers'}
                  <button onClick={() => refetch()} className="block mx-auto mt-2 text-xs text-blue-400 hover:underline">Retry</button>
                </div>
              ) : (
                <DataTable
                  data={displayedRows}
                  columns={columns as Parameters<typeof DataTable>[0]['columns']}
                  loading={isLoading}
                  emptyMessage={tab === 'active' ? "No active LLM model selected" : "No LLM providers configured yet"}
                />
              )}
            </Card>
          )}
        </div>
      </Can>

      <Modal open={formOpen} onClose={() => setFormOpen(false)} title={editing ? `Configure ${editing.name}` : 'Add Provider'} maxWidth="max-w-lg">
        <div className="space-y-3">
          {formError && <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">{formError}</div>}

          <div>
            <label className="text-[11px] font-medium text-white/50 mb-1 block">Name</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-medium text-white/50 mb-1 block">Provider</label>
              <select value={form.provider} disabled={!!editing} onChange={e => setForm(f => ({ ...f, provider: e.target.value }))}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50 disabled:opacity-50">
                <option value="">Select…</option>
                {(registry?.providers ?? []).map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-medium text-white/50 mb-1 block">Model</label>
              <input value={form.model} onChange={e => setForm(f => ({ ...f, model: e.target.value }))} placeholder="e.g. llama3, gpt-4o-mini"
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50" />
            </div>
          </div>

          <div>
            <label className="text-[11px] font-medium text-white/50 mb-1 block">Endpoint <span className="text-white/25">(optional — e.g. Ollama base URL)</span></label>
            <input value={form.endpoint} onChange={e => setForm(f => ({ ...f, endpoint: e.target.value }))} placeholder="http://localhost:11434"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50" />
          </div>

          <div>
            <label className="text-[11px] font-medium text-white/50 mb-1 block">API Key Env Var <span className="text-white/25">(name only — never the key itself)</span></label>
            <input value={form.api_key_env_var} onChange={e => setForm(f => ({ ...f, api_key_env_var: e.target.value }))} placeholder="OPENAI_API_KEY"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white placeholder:text-white/20 outline-none focus:border-blue-500/50" />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-[11px] font-medium text-white/50 mb-1 block">Temperature</label>
              <input type="number" step="0.1" min="0" max="2" value={form.temperature}
                onChange={e => setForm(f => ({ ...f, temperature: Number(e.target.value) }))}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50" />
            </div>
            <div>
              <label className="text-[11px] font-medium text-white/50 mb-1 block">Max Tokens</label>
              <input type="number" min="1" value={form.max_tokens ?? ''}
                onChange={e => setForm(f => ({ ...f, max_tokens: e.target.value ? Number(e.target.value) : undefined }))}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50" />
            </div>
            <div>
              <label className="text-[11px] font-medium text-white/50 mb-1 block">Context Window</label>
              <input type="number" min="1" value={form.context_window ?? ''}
                onChange={e => setForm(f => ({ ...f, context_window: e.target.value ? Number(e.target.value) : undefined }))}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50" />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <Btn variant="ghost" size="sm" onClick={() => setFormOpen(false)} disabled={saving}>Cancel</Btn>
            <Btn variant="primary" size="sm" onClick={submitForm} disabled={saving || !form.name || (!editing && !form.provider) || !form.model}>
              {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Provider'}
            </Btn>
          </div>
        </div>
      </Modal>
    </div>
  )
}
