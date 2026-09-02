'use client'
import { useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ChevronDown } from 'lucide-react'
import { PageHeader, Card, StatusBadge, EmptyState } from '@/components/shared/index'
import { documentsApi, evolutionApi, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

export default function DocumentsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const documentId = searchParams.get('id')
  const [pickerOpen, setPickerOpen] = useState(false)

  const { data: list } = useQuery({ queryKey: ['documents'], queryFn: () => documentsApi.list(0, 100) })

  const { data: doc, isLoading, isError, error } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => documentsApi.get(documentId as string),
    enabled: !!documentId,
  })

  const { data: versions } = useQuery({
    queryKey: ['document-versions', documentId],
    queryFn: () => evolutionApi.versions(documentId as string),
    enabled: !!documentId,
    retry: false,
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Document Details" description="Complete document metadata, versions, and extracted content">
        <div className="relative">
          <button onClick={() => setPickerOpen(!pickerOpen)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/[0.08] bg-white/[0.03] text-xs text-white/60 hover:text-white/90 transition-all">
            {documentId ?? 'Select a document'} <ChevronDown className="w-3.5 h-3.5" />
          </button>
          {pickerOpen && (
            <div className="absolute right-0 top-11 w-72 max-h-80 overflow-y-auto bg-[#12121f] border border-white/10 rounded-2xl shadow-2xl z-50">
              {(list?.documents ?? []).map(d => (
                <button key={d.document_id} onClick={() => { router.push(`/documents?id=${d.document_id}`); setPickerOpen(false) }}
                  className="w-full text-left px-4 py-2.5 text-xs text-white/60 hover:text-white hover:bg-white/[0.05] transition-all truncate">
                  {d.original_filename}
                </button>
              ))}
              {(list?.documents?.length ?? 0) === 0 && <p className="px-4 py-3 text-xs text-white/30">No documents uploaded yet</p>}
            </div>
          )}
        </div>
      </PageHeader>

      {!documentId && (
        <Card>
          <EmptyState icon={<ChevronDown className="w-5 h-5" />} title="No document selected" description="Choose a document above, or click a row in Knowledge Ingestion to view its details." />
        </Card>
      )}

      {documentId && isError && (
        <Card>
          <p className="text-sm text-red-400 text-center py-6">{error instanceof ApiError ? error.message : 'Failed to load document'}</p>
        </Card>
      )}

      {documentId && isLoading && (
        <Card><div className="h-40 animate-pulse bg-white/[0.03] rounded-xl" /></Card>
      )}

      {doc && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Metadata */}
          <Card className="lg:col-span-1">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center text-2xl">📄</div>
              <div className="min-w-0">
                <p className="text-sm font-bold text-white truncate">{doc.filename}</p>
                <p className="text-xs text-white/40">{doc.document_id}</p>
              </div>
            </div>
            <div className="space-y-3">
              {[
                { label: 'Status', value: <StatusBadge status={doc.processing_status} /> },
                { label: 'Department', value: doc.department ?? '—' },
                { label: 'Author', value: doc.author ?? '—' },
                { label: 'Language', value: doc.language?.toUpperCase() ?? '—' },
                { label: 'Version', value: `v${doc.version}` },
                { label: 'Word Count', value: doc.word_count.toLocaleString() },
                { label: 'Char Count', value: doc.character_count.toLocaleString() },
                { label: 'OCR', value: doc.ocr_used ? 'Used' : 'Not required' },
                { label: 'Uploaded', value: formatDateTime(doc.upload_date) },
              ].map(item => (
                <div key={item.label} className="flex items-center justify-between py-1.5 border-b border-white/[0.04]">
                  <span className="text-[11px] text-white/40">{item.label}</span>
                  <span className="text-xs text-white/70 font-medium">{item.value}</span>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <p className="text-[11px] text-white/40 mb-2">Permissions</p>
              <span className="text-[10px] bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded-full">{doc.permissions}</span>
            </div>
          </Card>

          {/* Content */}
          <div className="lg:col-span-2 space-y-4">
            <Card>
              <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Version History</h3>
              {versions && versions.versions.length > 0 ? (
                <div className="space-y-2">
                  {versions.versions.map((v, i) => (
                    <motion.div key={v.document_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                      className="flex items-start gap-3 p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                      <div className={`w-2.5 h-2.5 rounded-full mt-1 flex-shrink-0 ${v.is_latest ? 'bg-blue-400' : 'bg-gray-500'}`} />
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-white/80">v{v.version}</span>
                          <span className="text-[10px] text-white/30">{formatDateTime(v.upload_date)}</span>
                        </div>
                        <p className="text-[11px] text-white/50 mt-0.5">{v.word_count.toLocaleString()} words · {v.document_id}</p>
                      </div>
                      <StatusBadge status={v.is_latest ? 'current' : 'stable'} />
                    </motion.div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-white/30">Only one version on record.</p>
              )}
            </Card>

            <Card>
              <h3 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Extracted Text Preview</h3>
              <div className="bg-[#0a0a14] rounded-xl p-4 text-xs text-white/60 leading-relaxed max-h-64 overflow-y-auto font-mono whitespace-pre-wrap">
                {doc.extracted_text_preview || 'No preview available.'}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
