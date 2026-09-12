'use client'
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { CheckCircle, Circle, Loader2, XCircle, ChevronRight, Hash, Eye } from 'lucide-react'
import { PageHeader, Card, StatusBadge, EmptyState } from '@/components/shared/index'
import { documentsApi, chunksApi, evolutionApi, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

const stages = [
  { id: 'extract', label: 'Text Extraction', desc: 'Load & OCR fallback', icon: '📄' },
  { id: 'cleaning', label: 'Text Cleaning', desc: 'Remove noise, headers, footers', icon: '🧹' },
  { id: 'language', label: 'Language Detection', desc: 'Identify document language', icon: '🌐' },
  { id: 'chunking', label: 'Semantic Chunking', desc: 'Split into meaningful segments', icon: '✂️' },
  { id: 'indexing', label: 'Embedding + Index', desc: 'Vectorize & store in FAISS', icon: '🧠' },
]

export default function ProcessingPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'event' | 'chunks' | 'preview'>('chunks')

  const { data: list, isLoading: listLoading } = useQuery({
    queryKey: ['processing-documents'],
    queryFn: () => documentsApi.list(0, 50),
  })

  useEffect(() => {
    if (!selectedId && list?.documents.length) setSelectedId(list.documents[0].document_id)
  }, [list, selectedId])

  const { data: doc, isLoading: docLoading, isError: docError, error: docErrorObj } = useQuery({
    queryKey: ['processing-document', selectedId],
    queryFn: () => documentsApi.get(selectedId as string),
    enabled: !!selectedId,
  })

  const { data: chunkData, isLoading: chunksLoading } = useQuery({
    queryKey: ['processing-chunks', selectedId],
    queryFn: () => chunksApi.list(selectedId as string),
    enabled: !!selectedId,
  })

  const { data: eventData } = useQuery({
    queryKey: ['processing-event', selectedId],
    queryFn: () => evolutionApi.changes({ document_id: selectedId as string, limit: 1 }),
    enabled: !!selectedId,
  })
  const event = eventData?.events[0]

  // Map the document's real terminal status onto the pipeline stages —
  // there's no per-stage telemetry, so a failed doc shows failure at
  // extraction (the earliest possible failure point) rather than fabricating
  // which stage actually broke.
  const activeStage = doc?.processing_status === 'indexed' ? stages.length
    : doc?.processing_status === 'failed' ? 0
    : stages.length - 1
  const failed = doc?.processing_status === 'failed'

  return (
    <div className="space-y-6">
      <PageHeader title="Document Processing" description="Real ingestion pipeline status for each document" />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Document Selector */}
        <Card className="lg:col-span-1">
          <h3 className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider mb-3">Documents</h3>
          {listLoading ? (
            <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-12 rounded-xl bg-gray-100 dark:bg-white/[0.03] animate-pulse" />)}</div>
          ) : (list?.documents.length ?? 0) === 0 ? (
            <EmptyState icon={<Eye className="w-5 h-5" />} title="No documents yet" description="Upload one on the Knowledge Ingestion page." />
          ) : (
            <div className="space-y-1 max-h-[600px] overflow-y-auto">
              {list!.documents.map(d => (
                <button key={d.document_id} onClick={() => setSelectedId(d.document_id)}
                  className={`w-full flex items-center gap-2 p-2.5 rounded-xl text-left transition-all ${selectedId === d.document_id ? 'bg-blue-50 dark:bg-blue-600/20 border border-blue-200 dark:border-blue-500/20' : 'hover:bg-gray-50 dark:hover:bg-white/[0.03]'}`}>
                  <span className="text-sm">📄</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-900 dark:text-white/80 truncate">{d.original_filename}</p>
                    <p className="text-[10px] text-gray-400 dark:text-white/30">{d.department ?? 'Unassigned'}</p>
                  </div>
                  <StatusBadge status={d.processing_status} />
                </button>
              ))}
            </div>
          )}
        </Card>

        {/* Pipeline */}
        <div className="lg:col-span-2 space-y-4">
          {!selectedId ? (
            <Card><EmptyState icon={<Eye className="w-5 h-5" />} title="Select a document" /></Card>
          ) : docLoading ? (
            <Card><div className="h-40 animate-pulse bg-gray-100 dark:bg-white/[0.03] rounded-xl" /></Card>
          ) : doc ? (
            <>
              <Card>
                <h3 className="text-xs font-semibold text-gray-500 dark:text-white/50 uppercase tracking-wider mb-4">Processing Pipeline — {doc.filename}</h3>
                <div className="flex items-center gap-1">
                  {stages.map((stage, i) => {
                    const isFailedHere = failed && i === 0
                    const done = !failed && i < activeStage
                    const active = !failed && i === activeStage && doc.processing_status === 'processing'
                    return (
                      <div key={stage.id} className="flex items-center flex-1">
                        <div className={`flex-1 p-3 rounded-xl border transition-all ${isFailedHere ? 'bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/30' : done || activeStage === stages.length ? 'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20' : active ? 'bg-blue-50 border-blue-200 dark:bg-blue-500/10 dark:border-blue-500/30' : 'bg-gray-50 border-gray-200 dark:bg-white/[0.02] dark:border-white/[0.06]'}`}>
                          <div className="flex items-center gap-2 mb-1">
                            {isFailedHere ? <XCircle className="w-3.5 h-3.5 text-red-500 dark:text-red-400" /> : (done || activeStage === stages.length) ? <CheckCircle className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400" /> : active ? <Loader2 className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400 animate-spin" /> : <Circle className="w-3.5 h-3.5 text-gray-300 dark:text-white/20" />}
                            <span className="text-[10px]">{stage.icon}</span>
                          </div>
                          <p className={`text-[11px] font-semibold ${isFailedHere ? 'text-red-600 dark:text-red-400' : (done || activeStage === stages.length) ? 'text-emerald-600 dark:text-emerald-400' : active ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-white/30'}`}>{stage.label}</p>
                          <p className="text-[10px] text-gray-400 dark:text-white/25 mt-0.5 hidden xl:block">{stage.desc}</p>
                        </div>
                        {i < stages.length - 1 && <ChevronRight className="w-3 h-3 text-gray-300 dark:text-white/20 flex-shrink-0 mx-0.5" />}
                      </div>
                    )
                  })}
                </div>

                {/* Stats */}
                <div className="grid grid-cols-4 gap-3 mt-4">
                  {[
                    { label: 'Chunks', value: chunkData?.total ?? '—' },
                    { label: 'Words', value: doc.word_count.toLocaleString() },
                    { label: 'Language', value: doc.language?.toUpperCase() ?? '—' },
                    { label: 'OCR', value: doc.ocr_used ? '✓ used' : 'N/A' },
                  ].map(s => (
                    <div key={s.label} className="bg-gray-50 dark:bg-white/[0.03] rounded-xl p-3 text-center border border-gray-200/60 dark:border-transparent">
                      <p className="text-lg font-bold text-gray-900 dark:text-white">{s.value}</p>
                      <p className="text-[10px] text-gray-500 dark:text-white/30 font-medium">{s.label}</p>
                    </div>
                  ))}
                </div>
                {doc.extraction_duration_s != null && (
                  <p className="text-[11px] text-gray-400 dark:text-white/30 mt-3">Extraction took {doc.extraction_duration_s.toFixed(2)}s · uploaded {formatDateTime(doc.upload_date)} · version {doc.version}</p>
                )}
              </Card>

              {/* Tabs */}
              <Card>
                <div className="flex items-center gap-1 mb-4 bg-gray-100 dark:bg-white/[0.03] border border-gray-200 dark:border-white/[0.06] rounded-xl p-1 w-fit">
                  {(['chunks', 'event', 'preview'] as const).map(tab => (
                    <button key={tab} onClick={() => setActiveTab(tab)}
                      className={`px-4 py-1.5 rounded-lg text-xs font-medium capitalize transition-all ${activeTab === tab ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-500 dark:text-white/40 hover:text-gray-800 dark:hover:text-white/70'}`}>
                      {tab === 'chunks' ? '✂️ Chunks' : tab === 'event' ? '📋 Evolution Event' : '👁️ Preview'}
                    </button>
                  ))}
                </div>

                {activeTab === 'chunks' && (
                  chunksLoading ? (
                    <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-16 rounded-xl bg-gray-100 dark:bg-white/[0.03] animate-pulse" />)}</div>
                  ) : (chunkData?.chunks.length ?? 0) === 0 ? (
                    <p className="text-xs text-gray-400 dark:text-white/30 text-center py-8">No chunks stored for this document yet.</p>
                  ) : (
                    <div className="space-y-3 max-h-64 overflow-y-auto">
                      {chunkData!.chunks.map((chunk) => (
                        <motion.div key={chunk.id} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
                          className="p-3 bg-gray-50 dark:bg-white/[0.03] rounded-xl border border-gray-200 dark:border-white/[0.05]">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-[10px] bg-blue-50 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 font-semibold px-2 py-0.5 rounded-full font-mono">Chunk #{chunk.chunk_index}</span>
                            <span className="text-[10px] text-gray-500 dark:text-white/30"><Hash className="w-2.5 h-2.5 inline mr-0.5" />{chunk.word_count} words</span>
                            <span className={`text-[10px] ml-auto font-medium ${chunk.faiss_id != null ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400 dark:text-white/30'}`}>{chunk.faiss_id != null ? `✓ indexed (faiss #${chunk.faiss_id})` : 'not indexed'}</span>
                          </div>
                          <p className="text-xs text-gray-700 dark:text-white/60 leading-relaxed">{chunk.text}</p>
                        </motion.div>
                      ))}
                    </div>
                  )
                )}

                {activeTab === 'event' && (
                  event ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Chunks Added', value: event.chunks_added },
                          { label: 'Chunks Removed', value: event.chunks_removed },
                          { label: 'Chunks Unchanged', value: event.chunks_unchanged },
                        ].map(s => (
                          <div key={s.label} className="bg-gray-50 dark:bg-white/[0.03] rounded-xl p-3 text-center border border-gray-200/60 dark:border-transparent">
                            <p className="text-lg font-bold text-gray-900 dark:text-white">{s.value}</p>
                            <p className="text-[10px] text-gray-500 dark:text-white/30 font-medium">{s.label}</p>
                          </div>
                        ))}
                      </div>
                      <div className="text-xs text-gray-600 dark:text-white/50 space-y-1.5 p-3 bg-gray-50 dark:bg-white/[0.02] rounded-xl border border-gray-200/60 dark:border-transparent">
                        <p>Change type: <span className="text-gray-900 dark:text-white/80 font-semibold capitalize">{event.change_type.replace(/_/g, ' ')}</span></p>
                        <p>Detected: <span className="text-gray-800 dark:text-white/80">{formatDateTime(event.detected_at)}</span></p>
                        {event.drift_detected && <p className="text-amber-600 dark:text-amber-400 font-medium">⚠ Concept drift detected</p>}
                        {event.conflict_count > 0 && <p className="text-red-600 dark:text-red-400 font-medium">⚠ {event.conflict_count} conflict(s) found</p>}
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 dark:text-white/30 text-center py-8">No evolution event recorded for this document.</p>
                  )
                )}

                {activeTab === 'preview' && (
                  <div className="adaptive-code-block rounded-xl p-4 max-h-64 overflow-y-auto">
                    <p className="text-xs leading-relaxed whitespace-pre-wrap font-mono">
                      {doc.extracted_text_preview || 'No preview available.'}
                    </p>
                  </div>
                )}
              </Card>
            </>
          ) : docError ? (
            <Card><p className="text-sm text-red-500 dark:text-red-400 text-center py-6">{docErrorObj instanceof ApiError ? docErrorObj.message : 'Failed to load document'}</p></Card>
          ) : null}
        </div>
      </div>
    </div>
  )
}
