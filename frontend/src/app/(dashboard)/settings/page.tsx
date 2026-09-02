'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Settings, Moon, Sun, Bell, Key, User, Sliders, Brain, Database } from 'lucide-react'
import { PageHeader, Card } from '@/components/shared/index'
import { useTheme } from 'next-themes'
import { useAppStore } from '@/store/appStore'

export default function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const { currentUser } = useAppStore()
  const [model, setModel] = useState('gpt-4o')
  const [embeddingModel, setEmbeddingModel] = useState('text-embedding-3-large')
  const [chunkSize, setChunkSize] = useState(512)
  const [chunkOverlap, setChunkOverlap] = useState(50)
  const [language, setLanguage] = useState('en')
  const [notifications, setNotifications] = useState({ email: true, slack: false, webhook: true, alerts: true })

  return (
    <div className="space-y-6 max-w-3xl">
      <PageHeader title="Settings" description="Configure your platform preferences and integrations" />

      {/* Profile */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <User className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-white/70">Profile</h3>
        </div>
        <div className="flex items-center gap-4 mb-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center text-xl font-bold text-white">
            {currentUser?.name.split(' ').map(n => n[0]).join('')}
          </div>
          <div>
            <p className="text-sm font-semibold text-white">{currentUser?.name}</p>
            <p className="text-xs text-white/40">{currentUser?.email}</p>
            <span className="text-[10px] bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full capitalize">{currentUser?.role}</span>
          </div>
          <button className="ml-auto px-4 py-2 rounded-xl border border-white/[0.08] text-xs text-white/60 hover:text-white/80 hover:border-white/15 transition-all">Edit Profile</button>
        </div>
      </Card>

      {/* Appearance */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Settings className="w-4 h-4 text-violet-400" />
          <h3 className="text-sm font-semibold text-white/70">Appearance</h3>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-white/80">Theme</p>
            <p className="text-[11px] text-white/40">Choose your preferred color scheme</p>
          </div>
          <div className="flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] rounded-xl p-1">
            {[{ id: 'dark', icon: <Moon className="w-3.5 h-3.5" />, label: 'Dark' }, { id: 'light', icon: <Sun className="w-3.5 h-3.5" />, label: 'Light' }].map(t => (
              <button key={t.id} onClick={() => setTheme(t.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${theme === t.id ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                {t.icon} {t.label}
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* Model Config */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Brain className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-semibold text-white/70">Model Configuration</h3>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-white/80">LLM Model</p>
              <p className="text-[11px] text-white/40">Primary language model for generation</p>
            </div>
            <select value={model} onChange={e => setModel(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white/70 outline-none focus:border-blue-500/50 transition-all">
              {['gpt-4o', 'gpt-4-turbo', 'claude-3-opus', 'claude-3-sonnet', 'llama-3-70b', 'mistral-large'].map(m => (
                <option key={m} value={m} className="bg-[#12121f]">{m}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-white/80">Embedding Model</p>
              <p className="text-[11px] text-white/40">Model for vector generation</p>
            </div>
            <select value={embeddingModel} onChange={e => setEmbeddingModel(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white/70 outline-none focus:border-blue-500/50 transition-all">
              {['text-embedding-3-large', 'text-embedding-3-small', 'text-embedding-ada-002', 'e5-large-v2'].map(m => (
                <option key={m} value={m} className="bg-[#12121f]">{m}</option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {/* Chunking Config */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Sliders className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-white/70">Chunking Configuration</h3>
        </div>
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-white/80">Chunk Size</p>
              <span className="text-xs font-bold text-blue-400">{chunkSize} tokens</span>
            </div>
            <input type="range" min={128} max={2048} step={64} value={chunkSize} onChange={e => setChunkSize(Number(e.target.value))}
              className="w-full accent-blue-500" />
            <div className="flex justify-between text-[10px] text-white/25 mt-1"><span>128</span><span>2048</span></div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-white/80">Chunk Overlap</p>
              <span className="text-xs font-bold text-violet-400">{chunkOverlap} tokens</span>
            </div>
            <input type="range" min={0} max={256} step={16} value={chunkOverlap} onChange={e => setChunkOverlap(Number(e.target.value))}
              className="w-full accent-violet-500" />
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-white/80">Default Language</p>
              <p className="text-[11px] text-white/40">Primary language for processing</p>
            </div>
            <select value={language} onChange={e => setLanguage(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white/70 outline-none">
              {[{ v: 'en', l: 'English' }, { v: 'es', l: 'Spanish' }, { v: 'de', l: 'German' }, { v: 'fr', l: 'French' }, { v: 'zh', l: 'Chinese' }].map(l => (
                <option key={l.v} value={l.v} className="bg-[#12121f]">{l.l}</option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {/* Notifications */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Bell className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-white/70">Notifications</h3>
        </div>
        <div className="space-y-3">
          {[
            { key: 'email', label: 'Email Notifications', desc: 'Receive alerts via email' },
            { key: 'slack', label: 'Slack Integration', desc: 'Send notifications to Slack' },
            { key: 'webhook', label: 'Webhook Events', desc: 'POST events to custom endpoint' },
            { key: 'alerts', label: 'System Alerts', desc: 'Critical system health alerts' },
          ].map(item => (
            <div key={item.key} className="flex items-center justify-between py-2">
              <div>
                <p className="text-xs font-medium text-white/80">{item.label}</p>
                <p className="text-[11px] text-white/40">{item.desc}</p>
              </div>
              <button onClick={() => setNotifications(prev => ({ ...prev, [item.key]: !prev[item.key as keyof typeof prev] }))}
                className={`relative w-10 h-5 rounded-full transition-all ${notifications[item.key as keyof typeof notifications] ? 'bg-blue-600' : 'bg-white/[0.1]'}`}>
                <motion.div animate={{ x: notifications[item.key as keyof typeof notifications] ? 20 : 2 }}
                  className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm" />
              </button>
            </div>
          ))}
        </div>
      </Card>

      {/* API Keys */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-4 h-4 text-red-400" />
          <h3 className="text-sm font-semibold text-white/70">API Keys</h3>
        </div>
        <div className="space-y-3">
          {[
            { name: 'Production API Key', key: 'sk-prod-••••••••••••••••••••••••••••••••', created: '2024-11-01' },
            { name: 'Development API Key', key: 'sk-dev-••••••••••••••••••••••••••••••••', created: '2024-12-01' },
          ].map(k => (
            <div key={k.name} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.02] border border-white/[0.05]">
              <div className="flex-1">
                <p className="text-xs font-medium text-white/80">{k.name}</p>
                <p className="text-[11px] font-mono text-white/30 mt-0.5">{k.key}</p>
                <p className="text-[10px] text-white/20 mt-0.5">Created {k.created}</p>
              </div>
              <button className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors">Reveal</button>
              <button className="text-[11px] text-red-400/60 hover:text-red-400 transition-colors">Revoke</button>
            </div>
          ))}
          <button className="w-full py-2.5 rounded-xl border border-dashed border-white/[0.1] text-xs text-white/40 hover:text-white/60 hover:border-white/20 transition-all">
            + Generate New API Key
          </button>
        </div>
      </Card>

      <div className="flex gap-3">
        <button className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all">
          Save Changes
        </button>
        <button className="px-6 py-2.5 rounded-xl border border-white/[0.08] text-sm text-white/60 hover:text-white/80 transition-all">
          Reset to Defaults
        </button>
      </div>
    </div>
  )
}
