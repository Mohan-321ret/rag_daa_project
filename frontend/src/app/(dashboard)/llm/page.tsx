'use client'
import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Send, Bot, User, Copy, ThumbsUp, ThumbsDown, BookOpen, BarChart2, RefreshCw, ShieldCheck, AlertTriangle } from 'lucide-react'
import { PageHeader, Card, ConfidenceMeter } from '@/components/shared/index'
import { ragApi, llmApi, feedbackApi, ApiError, type RAGSource } from '@/lib/api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: RAGSource[]
  isGrounded?: boolean | null
  latency?: number | null
  route?: string | null
  queryId?: string | null
  feedback?: 'up' | 'down'
  error?: boolean
  timestamp: Date
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-4 py-3">
      {[0, 1, 2].map(i => (
        <motion.div key={i} animate={{ y: [0, -4, 0] }} transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
          className="w-1.5 h-1.5 rounded-full bg-blue-400" />
      ))}
    </div>
  )
}

export default function LLMPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: modelsData } = useQuery({ queryKey: ['llm-models'], queryFn: () => llmApi.models() })

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const question = input
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: question, timestamp: new Date() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    try {
      const result = await ragApi.query(question, model ? { model } : undefined)
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(), role: 'assistant',
        content: result.answer,
        sources: result.sources,
        isGrounded: result.is_grounded,
        latency: result.latency_ms,
        route: result.retrieval_route?.route,
        queryId: result.query_id,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, aiMsg])
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Something went wrong reaching the RAG pipeline.'
      setMessages(prev => [...prev, { id: (Date.now() + 1).toString(), role: 'assistant', content: message, error: true, timestamp: new Date() }])
    } finally {
      setLoading(false)
    }
  }

  const handleFeedback = async (msg: Message, rating: 'up' | 'down') => {
    if (!msg.queryId || msg.feedback) return
    setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, feedback: rating } : m))
    try {
      await feedbackApi.submit(msg.queryId, rating)
    } catch {
      setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, feedback: undefined } : m))
    }
  }

  const avgLatency = (() => {
    const withLatency = messages.filter(m => m.role === 'assistant' && m.latency)
    if (!withLatency.length) return null
    return Math.round(withLatency.reduce((s, m) => s + (m.latency ?? 0), 0) / withLatency.length)
  })()

  const allSources = messages.filter(m => m.sources).flatMap(m => m.sources ?? [])
    .filter((s, i, a) => a.findIndex(x => x.document_id === s.document_id) === i)

  return (
    <div className="flex gap-6 h-[calc(100vh-8rem)]">
      {/* Chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <PageHeader title="Enterprise LLM" description="RAG-powered conversational AI with grounded responses" />

        {/* Model Selector */}
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <button onClick={() => setModel(null)}
            className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${model === null ? 'bg-blue-600 text-white' : 'bg-white/[0.04] border border-white/[0.08] text-white/50 hover:text-white/80'}`}>
            default ({modelsData?.default_alias ?? '…'})
          </button>
          {(modelsData?.models ?? []).map(m => (
            <button key={m.alias} onClick={() => setModel(m.alias)} disabled={!m.available}
              title={m.available ? m.tag : `${m.tag} — not pulled on Ollama`}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed ${model === m.alias ? 'bg-blue-600 text-white' : 'bg-white/[0.04] border border-white/[0.08] text-white/50 hover:text-white/80'}`}>
              {m.alias}
            </button>
          ))}
          {(modelsData?.installed_raw ?? [])
            .filter(tag => !(modelsData?.models ?? []).some(m => m.tag === tag))
            .map(tag => (
              <button key={tag} onClick={() => setModel(tag)}
                title={`${tag} — installed on Ollama, not in the alias registry`}
                className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${model === tag ? 'bg-blue-600 text-white' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/15'}`}>
                {tag}
              </button>
            ))}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1">
          {messages.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center h-full text-center text-white/30">
              <Bot className="w-8 h-8 mb-2" />
              <p className="text-sm">Ask a question about your ingested documents to get started.</p>
            </div>
          )}
          {messages.map(msg => (
            <motion.div key={msg.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${msg.role === 'user' ? 'bg-gradient-to-br from-blue-500 to-violet-600' : 'bg-gradient-to-br from-emerald-500 to-teal-600'}`}>
                {msg.role === 'user' ? <User className="w-3.5 h-3.5 text-white" /> : <Bot className="w-3.5 h-3.5 text-white" />}
              </div>
              <div className={`max-w-[75%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
                <div className={`rounded-2xl px-4 py-3 ${msg.role === 'user' ? 'bg-blue-600/20 border border-blue-500/20' : msg.error ? 'bg-red-500/10 border border-red-500/20' : 'bg-white/[0.04] border border-white/[0.07]'}`}>
                  <p className="text-sm text-white/80 leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                </div>
                {msg.role === 'assistant' && !msg.error && (
                  <div className="flex items-center gap-3 px-1 flex-wrap">
                    {msg.latency && <span className="text-[10px] text-white/25">{Math.round(msg.latency)}ms</span>}
                    {msg.route && <span className="text-[10px] text-white/25 uppercase">{msg.route}</span>}
                    {msg.isGrounded !== null && msg.isGrounded !== undefined && (
                      <span className={`text-[10px] flex items-center gap-1 ${msg.isGrounded ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {msg.isGrounded ? <ShieldCheck className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                        {msg.isGrounded ? 'Grounded' : 'Ungrounded'}
                      </span>
                    )}
                    <button onClick={() => navigator.clipboard.writeText(msg.content)} className="text-white/20 hover:text-white/50 transition-colors"><Copy className="w-3 h-3" /></button>
                    <button onClick={() => handleFeedback(msg, 'up')} disabled={!msg.queryId}
                      className={`transition-colors disabled:opacity-30 ${msg.feedback === 'up' ? 'text-emerald-400' : 'text-white/20 hover:text-emerald-400'}`}><ThumbsUp className="w-3 h-3" /></button>
                    <button onClick={() => handleFeedback(msg, 'down')} disabled={!msg.queryId}
                      className={`transition-colors disabled:opacity-30 ${msg.feedback === 'down' ? 'text-red-400' : 'text-white/20 hover:text-red-400'}`}><ThumbsDown className="w-3 h-3" /></button>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
          {loading && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0">
                <Bot className="w-3.5 h-3.5 text-white" />
              </div>
              <div className="bg-white/[0.04] border border-white/[0.07] rounded-2xl">
                <TypingIndicator />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex items-end gap-3 bg-white/[0.03] border border-white/[0.08] rounded-2xl p-3 focus-within:border-blue-500/40 transition-all">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder="Ask anything about your enterprise knowledge base..."
            rows={2}
            className="flex-1 bg-transparent text-sm text-white placeholder:text-white/25 outline-none resize-none"
          />
          <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
            onClick={handleSend} disabled={!input.trim() || loading}
            className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-violet-600 flex items-center justify-center text-white disabled:opacity-40 transition-all flex-shrink-0">
            <Send className="w-4 h-4" />
          </motion.button>
        </div>
      </div>

      {/* Side Panel */}
      <div className="w-72 flex-shrink-0 space-y-4 overflow-y-auto">
        <Card>
          <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Session Stats</h3>
          <div className="space-y-3">
            {[
              { label: 'Messages', value: messages.length },
              { label: 'Avg Latency', value: avgLatency ? `${avgLatency}ms` : '—' },
              { label: 'Provider', value: modelsData?.provider ?? '—' },
              { label: 'Model', value: model ?? modelsData?.default_alias ?? '—' },
            ].map(s => (
              <div key={s.label} className="flex items-center justify-between">
                <span className="text-xs text-white/40">{s.label}</span>
                <span className="text-xs font-semibold text-white/70">{s.value}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-2 mb-3">
            <BookOpen className="w-3.5 h-3.5 text-blue-400" />
            <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider">Citations</h3>
          </div>
          <div className="space-y-2">
            {allSources.length === 0 && <p className="text-[11px] text-white/25">No citations yet</p>}
            {allSources.map((src, i) => (
              <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-white/[0.03]">
                <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded font-mono flex-shrink-0">[{i + 1}]</span>
                <div className="min-w-0">
                  <p className="text-[11px] text-white/60 leading-tight truncate">{src.document_id}</p>
                  <div className="mt-1 w-16"><ConfidenceMeter value={src.score} size="sm" showLabel={false} /></div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 className="w-3.5 h-3.5 text-violet-400" />
            <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider">RAG Status</h3>
          </div>
          <RagStatusPanel />
        </Card>

        <button onClick={() => setMessages([])} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-white/[0.08] text-xs text-white/40 hover:text-white/70 hover:border-white/15 transition-all">
          <RefreshCw className="w-3.5 h-3.5" /> New Conversation
        </button>
      </div>
    </div>
  )
}

function RagStatusPanel() {
  const { data } = useQuery({ queryKey: ['rag-status'], queryFn: () => ragApi.status(), refetchInterval: 30000 })
  if (!data) return <p className="text-[11px] text-white/25">Loading…</p>
  return (
    <div className="space-y-2 text-[11px] text-white/50">
      <div className="flex justify-between"><span>Status</span><span className="text-white/70 font-medium capitalize">{data.status}</span></div>
      <div className="flex justify-between"><span>Indexed chunks</span><span className="text-white/70 font-medium">{data.total_indexed_chunks.toLocaleString()}</span></div>
      <div className="flex justify-between"><span>Provider</span><span className="text-white/70 font-medium">{data.llm_provider}</span></div>
    </div>
  )
}
