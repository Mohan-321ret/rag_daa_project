/**
 * Typed client for the FinalYear FastAPI backend (`/api/v1`).
 * Base URL comes from NEXT_PUBLIC_API_URL (see .env.local).
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
const TOKEN_KEY = 'daa_rag_token'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_URL}${path}`, { ...options, headers })

  if (!res.ok) {
    if (res.status === 401 && typeof window !== 'undefined' && !path.startsWith('/auth/')) {
      clearToken()
      window.location.href = '/login'
    }
    let detail: unknown
    try { detail = await res.json() } catch { /* no json body */ }
    let message = `Request failed with status ${res.status}`
    if (detail && typeof detail === 'object') {
      if ('detail' in detail) {
        const d = (detail as { detail: unknown }).detail
        message = typeof d === 'string' ? d : JSON.stringify(d)
      } else if ('error' in detail && detail.error && typeof detail.error === 'object' && 'message' in detail.error) {
        message = String((detail.error as { message: unknown }).message)
      } else {
        message = JSON.stringify(detail)
      }
    }
    throw new ApiError(res.status, message, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T>(path: string) => request<T>(path, { method: 'GET' })
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined })
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface DomainRef { id: string; key: string; name: string }

export interface UserOut {
  id: string; email: string; full_name: string | null; created_at: string
  auth_provider: string; picture: string | null; role: string; is_active: boolean
  status: 'active' | 'inactive'; department: string | null; domains: DomainRef[]
  updated_at: string | null; last_login: string | null
}
export interface TokenResponse { access_token: string; token_type: string; expires_in: number; user: UserOut }

export const authApi = {
  register: (email: string, password: string, full_name?: string) =>
    post<TokenResponse>('/auth/register', { email, password, full_name }),
  login: (email: string, password: string) =>
    post<TokenResponse>('/auth/login', { email, password }),
  /** Exchange a Google Identity Services ID token for an app JWT. */
  google: (credential: string) => post<TokenResponse>('/auth/google', { credential }),
  me: () => get<UserOut>('/auth/me'),
}

// ── Documents ────────────────────────────────────────────────────────────────

export interface DocumentListItem {
  document_id: string
  original_filename: string
  document_type: string
  word_count: number
  processing_status: string
  upload_date: string
  ocr_used: boolean
  department: string | null
  domain_id: string | null
  visibility: 'global' | 'domain' | 'restricted'
  language: string | null
  version: number
}

export interface DocumentListResponse {
  total: number
  skip: number
  limit: number
  documents: DocumentListItem[]
}

export interface DocumentDetail {
  document_id: string
  filename: string
  document_type: string
  author: string | null
  title: string | null
  department: string | null
  domain_id: string | null
  visibility: 'global' | 'domain' | 'restricted'
  permissions: string
  owner_id: string | null
  uploaded_by_id: string | null
  language: string | null
  upload_date: string
  ocr_used: boolean
  word_count: number
  character_count: number
  extraction_duration_s: number | null
  processing_status: string
  version: number
  is_latest: boolean
  previous_version_id: string | null
  content_hash: string | null
  created_at: string
  updated_at: string
  extracted_text_preview: string | null
}

export interface UploadOptions {
  department?: string
  domain_id?: string          // required unless visibility === 'global'
  visibility?: 'global' | 'domain' | 'restricted'
  permissions?: string        // legacy free-text label
  restricted_user_ids?: string[]   // visibility === 'restricted' only
  language?: string
}

/**
 * POST /documents/upload returns this immediately (202) — a receipt, not a
 * confirmation. The upload is a genuine background job (Admin Panel: Data
 * Injection Management); poll ingestionJobsApi.get(job_id) for real
 * per-stage progress and the eventual document_id.
 */
export interface UploadAcceptedResponse {
  success: boolean
  job_id: string
  status: string
  original_filename: string
  message: string
}

function uploadForm(file: File, opts?: UploadOptions): FormData {
  const form = new FormData()
  form.append('file', file)
  if (opts?.department) form.append('department', opts.department)
  if (opts?.domain_id) form.append('domain_id', opts.domain_id)
  if (opts?.visibility) form.append('visibility', opts.visibility)
  if (opts?.permissions) form.append('permissions', opts.permissions)
  if (opts?.restricted_user_ids?.length) form.append('restricted_user_ids', opts.restricted_user_ids.join(','))
  if (opts?.language) form.append('language', opts.language)
  return form
}

export const documentsApi = {
  /** Kicks off the async ingestion job — returns 202 immediately, not the final document. */
  upload: (file: File, opts?: UploadOptions) =>
    request<UploadAcceptedResponse>('/documents/upload', { method: 'POST', body: uploadForm(file, opts) }),
  /** Same as `upload`, but reports real upload progress (0-100) via XHR. */
  uploadWithProgress: (
    file: File,
    opts: UploadOptions | undefined,
    onProgress: (pct: number) => void,
  ) => {
    const form = uploadForm(file, opts)

    return new Promise<UploadAcceptedResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${API_URL}/documents/upload`)
      const token = getToken()
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        let body: unknown
        try { body = JSON.parse(xhr.responseText) } catch { body = undefined }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body as UploadAcceptedResponse)
        } else {
          const message =
            body && typeof body === 'object' && 'detail' in body
              ? String((body as { detail: unknown }).detail)
              : `Upload failed with status ${xhr.status}`
          reject(new ApiError(xhr.status, message, body))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, 'Network error during upload'))
      xhr.send(form)
    })
  },
  list: (skip = 0, limit = 50, domainId?: string) =>
    get<DocumentListResponse>(`/documents/?skip=${skip}&limit=${limit}${domainId ? `&domain_id=${domainId}` : ''}`),
  get: (documentId: string) => get<DocumentDetail>(`/documents/${documentId}`),
}

// ── Ingestion Jobs (Admin Panel: Data Injection Management) ────────────────

export interface StageLogEntry {
  stage: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  started_at: string | null
  ended_at: string | null
  error: string | null
}

export type IngestionJobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'

export interface IngestionJobOut {
  job_id: string
  document_id: string | null
  original_filename: string
  status: IngestionJobStatus
  current_stage: string | null
  stage_log: StageLogEntry[]
  error_message: string | null
  action: string | null
  retry_of_job_id: string | null
  retry_count: number
  created_by: string | null
  created_at: string
  updated_at: string | null
  completed_at: string | null
}

export interface IngestionJobListResponse { total: number; skip: number; limit: number; jobs: IngestionJobOut[] }

export interface IngestionJobStatsResponse {
  total_documents: number
  queued: number
  processing: number
  completed: number
  failed: number
  cancelled: number
  failed_ingestion_count: number
  last_ingestion_at: string | null
}

export interface RetryJobResponse { success: boolean; job_id: string; retry_of_job_id: string; status: string; message: string }
export interface CancelJobResponse { success: boolean; job_id: string; status: string; message: string }

/** The full Admin Panel: Data Injection Management pipeline, in order. */
export const INGESTION_PIPELINE_STAGES = [
  'upload', 'document_loader', 'ocr', 'text_cleaning', 'noise_removal',
  'language_detection', 'chunking', 'embedding', 'vector_index',
  'postgres_metadata', 'neo4j',
] as const

export const ingestionJobsApi = {
  list: (opts?: { status?: IngestionJobStatus; skip?: number; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.status) params.set('status', opts.status)
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<IngestionJobListResponse>(`/ingestion-jobs/${qs ? `?${qs}` : ''}`)
  },
  stats: () => get<IngestionJobStatsResponse>('/ingestion-jobs/stats'),
  get: (jobId: string) => get<IngestionJobOut>(`/ingestion-jobs/${jobId}`),
  retry: (jobId: string) => post<RetryJobResponse>(`/ingestion-jobs/${jobId}/retry`),
  cancel: (jobId: string) => post<CancelJobResponse>(`/ingestion-jobs/${jobId}/cancel`),
}

// ── Chunks ───────────────────────────────────────────────────────────────────

export interface ChunkOut {
  id: string; document_id: string; chunk_index: number; text: string
  char_start: number; char_end: number; word_count: number
  faiss_id: number | null; created_at: string
}
export interface ChunkListResponse { document_id: string; total: number; chunks: ChunkOut[] }

export const chunksApi = {
  list: (documentId: string) => get<ChunkListResponse>(`/chunks/${documentId}`),
}

// ── Chunk Indexing Management (Admin Panel) ─────────────────────────────────

export type ChunkIndexStatus = 'indexed' | 'pending' | 'failed' | 'stale'
export type ReindexJobType = 'chunks' | 'document' | 'domain' | 'retry_failed' | 'remove_stale' | 'full_rebuild'
export type ReindexJobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'

export interface ChunkIndexStatsResponse {
  total_chunks: number
  indexed_chunks: number
  pending_chunks: number
  failed_chunks: number
  stale_chunks: number
  embedding_model: string
  embedding_dimension: number
  index_status: string
  faiss_total_vectors: number
  faiss_active_vectors: number
  last_indexing_time: string | null
}

export interface ChunkInspectOut {
  id: string
  document_id: string
  chunk_index: number
  text: string
  word_count: number
  document_version: number | null
  domain_id: string | null
  visibility: string | null
  index_status: ChunkIndexStatus
  faiss_id: number | null
  indexed_at: string | null
  created_at: string
}
export interface ChunkInspectListResponse { total: number; skip: number; limit: number; chunks: ChunkInspectOut[] }

export interface ReindexErrorEntry { ref: string; error: string | null; at: string }

export interface ReindexJobOut {
  job_id: string
  job_type: ReindexJobType
  status: ReindexJobStatus
  scope_document_id: string | null
  scope_domain_id: string | null
  scope_chunk_ids: string[] | null
  total_items: number
  processed_items: number
  failed_items: number
  error_log: ReindexErrorEntry[]
  error_message: string | null
  created_by: string | null
  created_at: string
  updated_at: string | null
  completed_at: string | null
}
export interface ReindexJobListResponse { total: number; skip: number; limit: number; jobs: ReindexJobOut[] }

export interface ReindexAcceptedResponse {
  success: boolean; job_id: string; job_type: ReindexJobType; status: string; total_items: number; message: string
}
export interface CancelReindexJobResponse { success: boolean; job_id: string; status: string; message: string }

export const chunkIndexingApi = {
  stats: () => get<ChunkIndexStatsResponse>('/chunk-indexing/stats'),
  listChunks: (opts?: {
    q?: string; domain_id?: string; document_id?: string; version?: number
    status?: ChunkIndexStatus; skip?: number; limit?: number
  }) => {
    const params = new URLSearchParams()
    if (opts?.q) params.set('q', opts.q)
    if (opts?.domain_id) params.set('domain_id', opts.domain_id)
    if (opts?.document_id) params.set('document_id', opts.document_id)
    if (opts?.version !== undefined) params.set('version', String(opts.version))
    if (opts?.status) params.set('status', opts.status)
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<ChunkInspectListResponse>(`/chunk-indexing/chunks${qs ? `?${qs}` : ''}`)
  },
  listJobs: (opts?: { status?: ReindexJobStatus; skip?: number; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.status) params.set('status', opts.status)
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<ReindexJobListResponse>(`/chunk-indexing/jobs${qs ? `?${qs}` : ''}`)
  },
  getJob: (jobId: string) => get<ReindexJobOut>(`/chunk-indexing/jobs/${jobId}`),
  reindexChunks: (chunkIds: string[]) => post<ReindexAcceptedResponse>('/chunk-indexing/reindex/chunks', { chunk_ids: chunkIds }),
  reindexDocument: (documentId: string) => post<ReindexAcceptedResponse>(`/chunk-indexing/reindex/document/${documentId}`),
  reindexDomain: (domainId: string) => post<ReindexAcceptedResponse>(`/chunk-indexing/reindex/domain/${domainId}`),
  retryFailed: (opts?: { document_id?: string; domain_id?: string }) => {
    const params = new URLSearchParams()
    if (opts?.document_id) params.set('document_id', opts.document_id)
    if (opts?.domain_id) params.set('domain_id', opts.domain_id)
    const qs = params.toString()
    return post<ReindexAcceptedResponse>(`/chunk-indexing/retry-failed${qs ? `?${qs}` : ''}`)
  },
  removeStale: (opts?: { document_id?: string; domain_id?: string }) => {
    const params = new URLSearchParams()
    if (opts?.document_id) params.set('document_id', opts.document_id)
    if (opts?.domain_id) params.set('domain_id', opts.domain_id)
    const qs = params.toString()
    return post<ReindexAcceptedResponse>(`/chunk-indexing/remove-stale${qs ? `?${qs}` : ''}`)
  },
  rebuild: () => post<ReindexAcceptedResponse>('/chunk-indexing/rebuild'),
  cancelJob: (jobId: string) => post<CancelReindexJobResponse>(`/chunk-indexing/jobs/${jobId}/cancel`),
}

// ── Health ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string; app: string; environment: string
  services: Record<string, string>
}

export const healthApi = {
  check: () => get<HealthResponse>('/health'),
}

// ── RAG ──────────────────────────────────────────────────────────────────────

export interface RAGSource { document_id: string; chunk_index: number | null; score: number; text_preview: string }
export interface RAGCitation { document_id: string; chunk_index: number | null; text_preview: string; source: string }

export interface RAGQueryResponse {
  query: string
  answer: string
  sources: RAGSource[]
  retrieved_chunks: number
  total_indexed: number
  provider: string
  query_id: string | null
  latency_ms: number | null
  query_analysis: Record<string, unknown> | null
  retrieval_route: { route: string; reason: string; signals: string[] } | null
  context_fusion: Record<string, unknown> | null
  model_used: string | null
  is_grounded: boolean | null
  citations: RAGCitation[]
  verification: Record<string, unknown> | null
  confidence_score?: number | null
  ticket: { ticket_id: string; department: string; status: string } | null
}

export const ragApi = {
  query: (question: string, opts?: { top_k?: number; document_id?: string; model?: string }) =>
    post<RAGQueryResponse>('/rag/query', { question, ...opts }),
  status: () => get<{ status: string; total_indexed_chunks: number; llm_provider: string; message: string }>('/rag/status'),
}

// ── Adaptive Retrieval ───────────────────────────────────────────────────────

export interface RetrievedChunkOut {
  document_id: string; chunk_index: number; text_preview: string; score: number
  source: string; metadata: Record<string, unknown>
}
export interface RetrievalRouteResponse {
  query: string
  route: { route: string; reason: string; signals: string[] }
  route_counts: Record<string, number>
  results: RetrievedChunkOut[]
}

export const retrievalApi = {
  route: (query: string, opts?: { top_k?: number; document_id?: string }) =>
    post<RetrievalRouteResponse>('/retrieval/route', { query, ...opts }),
}

// ── Query Intelligence ───────────────────────────────────────────────────────

export interface QueryAnalysisResponse {
  raw_query: string
  normalized_query: string
  sub_questions: string[]
  intent: { intent: string; confidence: number; method: string }
  entities: { text: string; label: string; start: number; end: number }[]
  complexity: { level: string; score: number; factors: Record<string, unknown> }
  temporal: { has_temporal: boolean; scope: string; expressions: string[]; years: number[] }
  suggested_top_k: number
}

export const queryIntelligenceApi = {
  analyze: (query: string, top_k = 5) => post<QueryAnalysisResponse>('/query/analyze', { query, top_k }),
}

// ── Context Fusion ───────────────────────────────────────────────────────────

export interface FusedChunkOut {
  document_id: string; chunk_index: number; text: string; score: number; source: string
  original_char_count: number | null; compressed_char_count: number | null
}
export interface ContextFusionStatsOut {
  chunks_in: number; chars_in: number; duplicates_removed: number; chunks_after_dedup: number
  cross_encoder_applied: boolean; chunks_dropped_for_budget: number; chunks_out: number
  chars_out: number; compression_ratio: number
}
export interface ContextFuseResponse {
  query: string
  retrieval_route: Record<string, unknown>
  stats: ContextFusionStatsOut
  optimized_context: string
  chunks: FusedChunkOut[]
}

export const contextFusionApi = {
  fuse: (query: string, opts?: { top_k?: number; document_id?: string }) =>
    post<ContextFuseResponse>('/context/fuse', { query, ...opts }),
}

// ── Evidence Verification ───────────────────────────────────────────────────

export interface ClaimVerificationOut {
  claim: string; is_quantitative: boolean; status: string; claim_values: string[]
  evidence_document_id: string | null; evidence_text: string | null
  evidence_values: string[]; statement_similarity: number
}
export interface VerifyResponse {
  original_answer: string; final_answer: string; was_rewritten: boolean
  confidence_score: number; claims_total: number; claims_checked: number
  verifications: ClaimVerificationOut[]; hallucinations: ClaimVerificationOut[]
  corrections: { original: string; corrected: string; evidence_document_id: string }[]
}

export const verificationApi = {
  verify: (answer: string, document_id?: string) =>
    post<VerifyResponse>('/verification/verify', { answer, document_id }),
}

// ── Knowledge Evolution ──────────────────────────────────────────────────────

export interface ChangeEventSummary {
  event_id: string; change_type: string; filename: string
  old_document_id: string | null; new_document_id: string | null
  version_from: number | null; version_to: number | null; source: string
  text_similarity: number | null; embedding_similarity: number | null
  drift_detected: boolean; conflict_count: number
  chunks_added: number; chunks_removed: number; chunks_unchanged: number
  detected_at: string
}
export interface ChangeEventListResponse { total: number; events: ChangeEventSummary[] }
export interface ChangeEventDetail extends ChangeEventSummary {
  lines_added: number; lines_removed: number; lines_modified: number
  unified_diff: string | null
  drifted_chunks: Record<string, unknown>[]
  conflicts: Record<string, unknown>[]
  embeddings_reused: number; embeddings_computed: number
}
export interface WatcherStatusResponse {
  running: boolean; watch_dir: string; poll_interval_s: number
  last_scan: string | null; files_tracked: number; files_ingested: number; recent_events: unknown[]
}
export interface VersionInfo {
  document_id: string; version: number; is_latest: boolean; content_hash: string | null
  previous_version_id: string | null; word_count: number; processing_status: string; upload_date: string
}
export interface VersionHistoryResponse { original_filename: string; total_versions: number; versions: VersionInfo[] }
export interface CompareResponse {
  old_document_id: string; new_document_id: string
  diff: Record<string, unknown>; drift: Record<string, unknown>
  conflicts: Record<string, unknown>[]; conflict_count: number
}

export const evolutionApi = {
  changes: (opts?: { skip?: number; limit?: number; change_type?: string; document_id?: string }) => {
    const params = new URLSearchParams()
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.change_type) params.set('change_type', opts.change_type)
    if (opts?.document_id) params.set('document_id', opts.document_id)
    const qs = params.toString()
    return get<ChangeEventListResponse>(`/evolution/changes${qs ? `?${qs}` : ''}`)
  },
  changeDetail: (eventId: string) => get<ChangeEventDetail>(`/evolution/changes/${eventId}`),
  versions: (documentId: string) => get<VersionHistoryResponse>(`/evolution/versions/${documentId}`),
  compare: (oldDocumentId: string, newDocumentId: string) =>
    post<CompareResponse>('/evolution/compare', { old_document_id: oldDocumentId, new_document_id: newDocumentId }),
  watcherStatus: () => get<WatcherStatusResponse>('/evolution/watcher'),
  watcherStart: () => post<WatcherStatusResponse>('/evolution/watcher/start'),
  watcherStop: () => post<WatcherStatusResponse>('/evolution/watcher/stop'),
}

// ── Enterprise LLM ───────────────────────────────────────────────────────────

export interface ModelInfo { alias: string; tag: string; available: boolean }
export interface ModelsResponse {
  provider: string; default_alias: string; default_tag: string
  models: ModelInfo[]; installed_raw: string[]
}

export const llmApi = {
  models: () => get<ModelsResponse>('/llm/models'),
}

// ── LLM Management (Admin Panel: LLM and Model Switching) ──────────────────

export interface LLMProviderConfigOut {
  id: string
  name: string
  provider: string
  model: string
  endpoint: string | null
  api_key_env_var: string | null
  api_key_configured: boolean
  temperature: number
  max_tokens: number | null
  context_window: number | null
  status: 'active' | 'inactive'
  is_current: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}
export interface LLMProviderListResponse { total: number; providers: LLMProviderConfigOut[] }

export interface LLMProviderCreate {
  name: string
  provider: string
  model: string
  endpoint?: string
  api_key_env_var?: string
  temperature?: number
  max_tokens?: number
  context_window?: number
}
export interface LLMProviderUpdate {
  name?: string
  model?: string
  endpoint?: string
  api_key_env_var?: string
  temperature?: number
  max_tokens?: number
  context_window?: number
}

export interface ProviderRegistryResponse { providers: string[] }
export interface SwitchActiveResponse { success: boolean; id: string; name: string; provider: string; model: string; message: string }
export interface TestConnectionResponse { success: boolean; message: string; latency_ms: number | null; model_used: string }

export const llmConfigApi = {
  registry: () => get<ProviderRegistryResponse>('/llm-providers/registry'),
  list: () => get<LLMProviderListResponse>('/llm-providers/'),
  get: (id: string) => get<LLMProviderConfigOut>(`/llm-providers/${id}`),
  create: (body: LLMProviderCreate) => post<LLMProviderConfigOut>('/llm-providers/', body),
  update: (id: string, body: LLMProviderUpdate) => patch<LLMProviderConfigOut>(`/llm-providers/${id}`, body),
  activate: (id: string) => post<LLMProviderConfigOut>(`/llm-providers/${id}/activate`),
  deactivate: (id: string) => post<LLMProviderConfigOut>(`/llm-providers/${id}/deactivate`),
  switchActive: (id: string) => post<SwitchActiveResponse>(`/llm-providers/${id}/switch-active`),
  testConnection: (id: string) => post<TestConnectionResponse>(`/llm-providers/${id}/test-connection`),
}

// ── Continuous Learning / Feedback ──────────────────────────────────────────

export interface FeedbackSubmitResponse { feedback_id: string; query_id: string; rating: string; message: string }
export interface MetricsResponse {
  window_days: number | null; total_queries: number; total_rated: number
  user_satisfaction: number | null; hallucination_rate: number | null
  avg_latency_ms: number | null; p95_latency_ms: number | null
  queries_by_route: Record<string, number>
  retrieval_accuracy_by_route: Record<string, number | null>
  samples_by_route: Record<string, number>
}

// ── User & Access Management (RBAC Foundation) ──────────────────────────────

export interface UserListResponse { total: number; skip: number; limit: number; users: UserOut[] }
export interface UserUpdate {
  full_name?: string; department?: string; is_active?: boolean; role?: string; domain_ids?: string[]
}
export interface UserCreate {
  email: string; password: string; full_name?: string; department?: string
  role?: string; domain_ids?: string[]
}
export interface UserListFilters {
  q?: string; role?: string; domain_id?: string; status?: 'active' | 'inactive'
  skip?: number; limit?: number
}

export const usersApi = {
  list: (opts?: UserListFilters) => {
    const params = new URLSearchParams()
    if (opts?.q) params.set('q', opts.q)
    if (opts?.role) params.set('role', opts.role)
    if (opts?.domain_id) params.set('domain_id', opts.domain_id)
    if (opts?.status) params.set('status', opts.status)
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<UserListResponse>(`/users/${qs ? `?${qs}` : ''}`)
  },
  get: (userId: string) => get<UserOut>(`/users/${userId}`),
  create: (body: UserCreate) => post<UserOut>('/users/', body),
  update: (userId: string, body: UserUpdate) => patch<UserOut>(`/users/${userId}`, body),
}

// ── Domain Management ────────────────────────────────────────────────────────

export interface DomainOut {
  id: string; key: string; name: string; description: string | null
  is_active: boolean; created_at: string; updated_at: string
}
export interface DomainListResponse { total: number; domains: DomainOut[] }
export interface DomainCreate { key: string; name: string; description?: string }
export interface DomainUpdate { name?: string; description?: string; is_active?: boolean }

export const domainsApi = {
  list: (includeInactive = false) =>
    get<DomainListResponse>(`/domains/${includeInactive ? '?include_inactive=true' : ''}`),
  create: (body: DomainCreate) => post<DomainOut>('/domains/', body),
  update: (domainId: string, body: DomainUpdate) => patch<DomainOut>(`/domains/${domainId}`, body),
}

// ── Audit Log ────────────────────────────────────────────────────────────────

export interface AuditLogOut {
  id: string; event_type: string; actor_id: string | null; actor_email: string | null
  target_user_id: string | null; target_email: string | null
  before_value: string | null; after_value: string | null; detail: string | null
  created_at: string
}
export interface AuditLogListResponse { total: number; skip: number; limit: number; logs: AuditLogOut[] }

export const auditLogsApi = {
  list: (opts?: { event_type?: string; target_user_id?: string; skip?: number; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.event_type) params.set('event_type', opts.event_type)
    if (opts?.target_user_id) params.set('target_user_id', opts.target_user_id)
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<AuditLogListResponse>(`/audit-logs/${qs ? `?${qs}` : ''}`)
  },
}

// ── Permissions introspection ───────────────────────────────────────────────

export interface PermissionCatalogEntry { key: string; description: string }
export interface PermissionCategoryOut { key: string; label: string; permissions: PermissionCatalogEntry[] }
export interface PermissionRoleOut { key: string; rank: number; permissions: string[] }
export interface PermissionMatrixResponse { categories: PermissionCategoryOut[]; roles: PermissionRoleOut[] }

export const permissionsApi = {
  matrix: () => get<PermissionMatrixResponse>('/permissions/'),
}

// ── Query Logs Management (Phase 9: Query Logs and Query History) ────────────

export interface QueryLogListItem {
  query_id: string
  user_id?: string
  query_text: string
  answer_text?: string
  intent?: string
  complexity?: string
  route?: 'vector' | 'bm25' | 'graph' | 'hybrid'
  retrieval_strategy?: string
  model_used?: string
  confidence_score?: number
  is_grounded?: boolean
  was_rewritten: boolean
  hallucinations_detected: number
  retrieved_chunks: number
  citation_count: number
  verification_result?: 'verified' | 'partial' | 'unverified' | 'failed'
  ticket_status?: string
  latency_ms?: number
  created_at: string
}

export interface QueryLogDetail extends QueryLogListItem {
  user_role?: string
  user_domain?: string
  route_overridden: boolean
  retrieved_chunk_ids: string[]
  authorized_chunk_ids: string[]
  retrieval_score?: number
  reranking_score?: number
  reranking_explanation?: string
  verification_details?: string
  ticket_id?: string
  chunk_access_violations: number
  access_violation_details?: string
  retrieval_latency_ms?: number
  reranking_latency_ms?: number
  llm_latency_ms?: number
}

export interface QueryLogListResponse {
  total: number
  skip: number
  limit: number
  scope: 'own' | 'domain' | 'global'
  logs: QueryLogListItem[]
}

export interface QueryLogDetailResponse {
  log: QueryLogDetail
  can_view_sensitive: boolean
}

export interface QueryLogExportResponse {
  total_exported: number
  logs: QueryLogDetail[]
}

export const queryLogsApi = {
  list: (opts?: {
    skip?: number
    limit?: number
    intent?: string
    route?: string
    retrieval_strategy?: string
    model_used?: string
    user_role?: string
    user_domain?: string
    min_confidence?: number
    max_confidence?: number
    ticket_status?: string
    verification_result?: string
    is_grounded?: boolean
    was_rewritten?: boolean
    date_from?: string
    date_to?: string
    search_text?: string
    user_id?: string
  }) => {
    const params = new URLSearchParams()
    if (opts?.skip) params.set('skip', String(opts.skip))
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.intent) params.set('intent', opts.intent)
    if (opts?.route) params.set('route', opts.route)
    if (opts?.retrieval_strategy) params.set('retrieval_strategy', opts.retrieval_strategy)
    if (opts?.model_used) params.set('model_used', opts.model_used)
    if (opts?.user_role) params.set('user_role', opts.user_role)
    if (opts?.user_domain) params.set('user_domain', opts.user_domain)
    if (opts?.min_confidence !== undefined) params.set('min_confidence', String(opts.min_confidence))
    if (opts?.max_confidence !== undefined) params.set('max_confidence', String(opts.max_confidence))
    if (opts?.ticket_status) params.set('ticket_status', opts.ticket_status)
    if (opts?.verification_result) params.set('verification_result', opts.verification_result)
    if (opts?.is_grounded !== undefined) params.set('is_grounded', String(opts.is_grounded))
    if (opts?.was_rewritten !== undefined) params.set('was_rewritten', String(opts.was_rewritten))
    if (opts?.date_from) params.set('date_from', opts.date_from)
    if (opts?.date_to) params.set('date_to', opts.date_to)
    if (opts?.search_text) params.set('search_text', opts.search_text)
    if (opts?.user_id) params.set('user_id', opts.user_id)
    const qs = params.toString()
    return get<QueryLogListResponse>(`/query-logs/${qs ? `?${qs}` : ''}`)
  },
  get: (queryId: string) => get<QueryLogDetailResponse>(`/query-logs/${queryId}`),
  export: (opts?: {
    intent?: string
    route?: string
    retrieval_strategy?: string
    model_used?: string
    user_role?: string
    user_domain?: string
    min_confidence?: number
    max_confidence?: number
    ticket_status?: string
    verification_result?: string
    is_grounded?: boolean
    was_rewritten?: boolean
    date_from?: string
    date_to?: string
    search_text?: string
    limit?: number
  }) => {
    const params = new URLSearchParams()
    if (opts?.intent) params.set('intent', opts.intent)
    if (opts?.route) params.set('route', opts.route)
    if (opts?.retrieval_strategy) params.set('retrieval_strategy', opts.retrieval_strategy)
    if (opts?.model_used) params.set('model_used', opts.model_used)
    if (opts?.user_role) params.set('user_role', opts.user_role)
    if (opts?.user_domain) params.set('user_domain', opts.user_domain)
    if (opts?.min_confidence !== undefined) params.set('min_confidence', String(opts.min_confidence))
    if (opts?.max_confidence !== undefined) params.set('max_confidence', String(opts.max_confidence))
    if (opts?.ticket_status) params.set('ticket_status', opts.ticket_status)
    if (opts?.verification_result) params.set('verification_result', opts.verification_result)
    if (opts?.is_grounded !== undefined) params.set('is_grounded', String(opts.is_grounded))
    if (opts?.was_rewritten !== undefined) params.set('was_rewritten', String(opts.was_rewritten))
    if (opts?.date_from) params.set('date_from', opts.date_from)
    if (opts?.date_to) params.set('date_to', opts.date_to)
    if (opts?.search_text) params.set('search_text', opts.search_text)
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<QueryLogExportResponse>(`/query-logs/export/all${qs ? `?${qs}` : ''}`)
  },
}

// ── Automatic Ticketing (Phase 10, 11, 12, 13) ──────────────────────────────

export type TicketStatus = 'open' | 'needs_triage' | 'routed' | 'assigned' | 'in_progress' | 'in_review' | 'resolved' | 'closed' | 'rejected' | 'dismissed'

export type ResolutionType =
  | 'KNOWLEDGE_MISSING'
  | 'RETRIEVAL_FAILURE'
  | 'INCORRECT_GENERATION'
  | 'OUTDATED_DOCUMENT'
  | 'ACCESS_RESTRICTION'
  | 'DOCUMENT_CONFLICT'
  | 'USER_CLARIFICATION'
  | 'OTHER'

export const RESOLUTION_TYPE_LABELS: Record<ResolutionType, { label: string; description: string; color: string }> = {
  KNOWLEDGE_MISSING: {
    label: 'Knowledge Missing',
    description: 'Information is missing from the knowledge base.',
    color: 'bg-red-500/15 text-red-400 border-red-500/25',
  },
  RETRIEVAL_FAILURE: {
    label: 'Retrieval Failure',
    description: 'Relevant docs exist in KB, but retrieval failed to retrieve/rank them.',
    color: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  INCORRECT_GENERATION: {
    label: 'Incorrect Generation',
    description: 'Context was retrieved, but LLM generated an inaccurate or hallucinated answer.',
    color: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  OUTDATED_DOCUMENT: {
    label: 'Outdated Document',
    description: 'Document in KB is stale or superseded by new policy.',
    color: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  },
  ACCESS_RESTRICTION: {
    label: 'Access Restriction',
    description: 'User lacked permissions required to view the authoritative document.',
    color: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  },
  DOCUMENT_CONFLICT: {
    label: 'Document Conflict',
    description: 'Conflicting or inconsistent information between multiple documents.',
    color: 'bg-pink-500/15 text-pink-400 border-pink-500/25',
  },
  USER_CLARIFICATION: {
    label: 'User Clarification',
    description: 'User query was ambiguous and required follow-up clarification.',
    color: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  },
  OTHER: {
    label: 'Other',
    description: 'Other root cause or custom resolution.',
    color: 'bg-gray-500/15 text-gray-400 border-gray-500/25',
  },
}

export interface TicketOut {
  ticket_id: string
  query_id: string | null
  user_id?: string | null
  raised_by_user_id: string | null
  title?: string
  description?: string
  original_question?: string
  user_question?: string
  query_text: string
  generated_answer?: string | null
  answer_text: string | null
  confidence_score: number
  confidence_threshold?: number
  evidence?: string | null
  hallucinations_detected: number
  source_document_ids: string[]
  citations?: string[]
  domain?: string
  department: string
  priority?: string
  status: TicketStatus
  routed_domain_id?: string | null
  routing_confidence?: number | null
  routing_method?: string | null
  assigned_to: string | null
  assigned_domain_expert?: { id: string; email?: string; full_name?: string; role?: string } | null
  assigned_expert?: { id: string; email?: string; full_name?: string; role?: string } | null
  resolution?: string | null
  resolution_type?: ResolutionType | string | null
  supporting_evidence?: string | null
  supporting_document_ids?: string[]
  resolved_by?: string | null
  resolver_user_id?: string | null
  resolver_user?: { id: string; email?: string; full_name?: string; role?: string } | null
  feedback?: string | null
  internal_notes?: string | null
  reviewer_notes: string | null
  corrected_answer: string | null
  occurrence_count: number
  is_overdue?: boolean
  sla_hours?: number
  created_at: string
  updated_at: string
  resolved_at: string | null
}

export interface TicketListResponse { total: number; skip: number; limit: number; tickets: TicketOut[] }

export interface TicketStatsResponse {
  total: number
  open: number
  needs_triage?: number
  routed?: number
  assigned?: number
  in_progress?: number
  in_review: number
  resolved: number
  closed?: number
  dismissed: number
  rejected?: number
  unassigned_tickets?: number
  overdue_tickets?: number
  by_department: Record<string, number>
  by_domain?: Record<string, number>
  by_priority?: Record<string, number>
  by_resolution_type?: Record<string, number>
  avg_confidence_open: number | null
  avg_resolution_time_hours?: number | null
}

export interface TicketUpdate {
  status?: TicketStatus
  priority?: string
  assigned_to?: string
  resolution?: string
  resolution_type?: ResolutionType | string
  supporting_evidence?: string
  supporting_document_ids?: string[]
  reviewer_notes?: string
  internal_notes?: string
  feedback?: string
  corrected_answer?: string
}

export interface TicketResolveRequest {
  resolution: string
  resolution_type: ResolutionType | string
  internal_notes?: string
  supporting_evidence?: string
  supporting_document_ids?: string[]
}

export const ticketsApi = {
  list: (opts?: {
    status?: TicketStatus | string
    domain?: string
    department?: string
    priority?: string
    resolution_type?: string
    assigned_to?: string
    search?: string
    skip?: number
    limit?: number
  }) => {
    const params = new URLSearchParams()
    if (opts?.status) params.set('status', opts.status)
    if (opts?.domain) params.set('domain', opts.domain)
    if (opts?.department) params.set('department', opts.department)
    if (opts?.priority) params.set('priority', opts.priority)
    if (opts?.resolution_type) params.set('resolution_type', opts.resolution_type)
    if (opts?.assigned_to) params.set('assigned_to', opts.assigned_to)
    if (opts?.search) params.set('search', opts.search)
    if (opts?.skip !== undefined) params.set('skip', String(opts.skip))
    if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<TicketListResponse>(`/tickets/${qs ? `?${qs}` : ''}`)
  },
  stats: () => get<TicketStatsResponse>('/tickets/stats'),
  get: (ticketId: string) => get<TicketOut>(`/tickets/${ticketId}`),
  update: (ticketId: string, body: TicketUpdate) => patch<TicketOut>(`/tickets/${ticketId}`, body),
  resolve: (ticketId: string, body: TicketResolveRequest) => post<TicketOut>(`/tickets/${ticketId}/resolve`, body),
  close: (ticketId: string, body?: { feedback?: string }) => post<TicketOut>(`/tickets/${ticketId}/close`, body),
  notes: (ticketId: string, notes: string) => post<TicketOut>(`/tickets/${ticketId}/notes`, { notes }),
  createKnowledgeUpdate: (ticketId: string, body?: Partial<KnowledgeUpdateRequestCreate>) =>
    post<KnowledgeUpdateRequest>(`/tickets/${ticketId}/create-knowledge-update`, body || {}),
}

export const feedbackApi = {
  submit: (queryId: string, rating: 'up' | 'down', correctionText?: string) =>
    post<FeedbackSubmitResponse>('/feedback/submit', { query_id: queryId, rating, correction_text: correctionText }),
  metrics: (windowDays?: number) =>
    get<MetricsResponse>(`/feedback/metrics/summary${windowDays ? `?window_days=${windowDays}` : ''}`),
  // Phase 15: Extended analytics
  getExtendedMetrics: (windowDays?: number) =>
    get<ExtendedMetricsResponse>(`/feedback/metrics/extended${windowDays !== undefined ? `?window_days=${windowDays}` : ''}`),
  getConfidenceCalibration: (windowDays?: number) =>
    get<CalibrationBucket[]>(`/feedback/metrics/confidence-calibration${windowDays !== undefined ? `?window_days=${windowDays}` : ''}`),
}

// ── Knowledge Evolution & Update Requests (Phase 14) ─────────────────────────

export type KnowledgeUpdateStatus = 'pending_review' | 'approved' | 'rejected' | 'applied' | 'cancelled'

export interface KnowledgeUpdateRequest {
  id: string
  request_id: string
  ticket_id: string
  document_id?: string | null
  target_filename?: string | null
  domain?: string | null
  root_cause: string
  title: string
  description?: string | null
  suggested_resolution: string
  supporting_evidence?: string | null
  supporting_document_ids?: string[]
  status: KnowledgeUpdateStatus
  created_by_id?: string | null
  reviewed_by_id?: string | null
  created_by?: { id: string; email?: string; full_name?: string; role?: string } | null
  reviewed_by?: { id: string; email?: string; full_name?: string; role?: string } | null
  reviewed_at?: string | null
  admin_notes?: string | null
  applied_document_id?: string | null
  change_event_id?: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeUpdateRequestListResponse {
  total: number
  skip: number
  limit: number
  requests: KnowledgeUpdateRequest[]
}

export interface KnowledgeUpdateStatsResponse {
  total: number
  pending_review: number
  approved: number
  rejected: number
  applied: number
  cancelled: number
  by_root_cause: Record<string, number>
  by_domain: Record<string, number>
}

export interface KnowledgeUpdateRequestCreate {
  ticket_id: string
  document_id?: string
  target_filename?: string
  domain?: string
  root_cause?: string
  title: string
  description?: string
  suggested_resolution: string
  supporting_evidence?: string
  supporting_document_ids?: string[]
}

export interface KnowledgeUpdateRequestReview {
  action: 'approve' | 'reject' | 'cancel'
  admin_notes?: string
}

export interface KnowledgeUpdateRequestApply {
  updated_text: string
  target_filename?: string
  language_hint?: string
  admin_notes?: string
}

export interface KnowledgeUpdateApplyResponse {
  request: KnowledgeUpdateRequest
  evolution_result: {
    document_id: string
    event_id: string
    change_type: string
    version: number
    is_latest: boolean
    lines_added?: number
    lines_removed?: number
    drift_detected?: boolean
    conflict_count?: number
    reindex_status?: string
  }
}

export const knowledgeUpdatesApi = {
  list: (opts?: {
    status?: string
    domain?: string
    root_cause?: string
    ticket_id?: string
    document_id?: string
    search?: string
    skip?: number
    limit?: number
  }) => {
    const params = new URLSearchParams()
    if (opts?.status) params.set('status', opts.status)
    if (opts?.domain) params.set('domain', opts.domain)
    if (opts?.root_cause) params.set('root_cause', opts.root_cause)
    if (opts?.ticket_id) params.set('ticket_id', opts.ticket_id)
    if (opts?.document_id) params.set('document_id', opts.document_id)
    if (opts?.search) params.set('search', opts.search)
    if (opts?.skip !== undefined) params.set('skip', String(opts.skip))
    if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return get<KnowledgeUpdateRequestListResponse>(`/knowledge-updates/${qs ? `?${qs}` : ''}`)
  },
  stats: () => get<KnowledgeUpdateStatsResponse>('/knowledge-updates/stats'),
  get: (requestId: string) => get<KnowledgeUpdateRequest>(`/knowledge-updates/${requestId}`),
  review: (requestId: string, body: KnowledgeUpdateRequestReview) =>
    post<KnowledgeUpdateRequest>(`/knowledge-updates/${requestId}/review`, body),
  apply: (requestId: string, body: KnowledgeUpdateRequestApply) =>
    post<KnowledgeUpdateApplyResponse>(`/knowledge-updates/${requestId}/apply`, body),
}

// ── Phase 15/16 Types ──────────────────────────────────────────────────────────

export interface ExtendedMetricsResponse {
  window_days: number | null
  total_queries: number
  total_rated: number
  user_satisfaction: number | null
  hallucination_rate: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  retrieval_accuracy_by_route: Record<string, number>
  ticket_generation_rate: number | null
  ticket_resolution_rate: number | null
  domain_routing_accuracy: number | null
  avg_ticket_resolution_time_hours: number | null
  signal_counts: Record<string, number>
  total_tickets: number | null
  total_resolved: number | null
}

export interface CalibrationBucket {
  bucket_min: number
  actual_correctness_rate: number
  total: number
}

export interface LearningSignalOut {
  signal_id: string
  signal_type: string
  query_id: string | null
  ticket_id: string | null
  confidence_score: number | null
  was_correct: string | null
  retrieval_route: string | null
  intent: string | null
  created_at: string
}

export interface ThresholdHistoryOut {
  history_id: string
  metric_name: string
  old_value: number | null
  new_value: number
  reason: string
  source: string
  approved_by: string | null
  applied_at: string | null
  suggestion_id: string | null
  created_at: string
}

export const learningApi = {
  listSignals: (opts?: { signal_type?: string; query_id?: string; limit?: number; skip?: number }) => {
    const p = new URLSearchParams()
    if (opts?.signal_type) p.set('signal_type', opts.signal_type)
    if (opts?.query_id) p.set('query_id', opts.query_id)
    if (opts?.limit !== undefined) p.set('limit', String(opts.limit))
    if (opts?.skip !== undefined) p.set('skip', String(opts.skip))
    return get<{ signals: LearningSignalOut[]; total: number; signal_counts: Record<string, number> }>(`/learning/signals${p.toString() ? `?${p}` : ''}`)
  },
  getThresholdHistory: (source?: string): Promise<ThresholdHistoryOut[]> => {
    const qs = source ? `?source=${source}` : ''
    return get<ThresholdHistoryOut[]>(`/learning/threshold-history${qs}`)
  },
  getPendingSuggestions: () => get<ThresholdHistoryOut[]>('/learning/threshold-suggestions'),
  generateSuggestions: (window_days?: number) => {
    const qs = window_days !== undefined ? `?window_days=${window_days}` : ''
    return post<ThresholdHistoryOut[]>(`/learning/threshold-suggestions/generate${qs}`)
  },
  applyThreshold: (suggestion_id: string) =>
    post<{ applied_history_id: string; metric_name: string; old_value: number; new_value: number; message: string }>('/learning/threshold-apply', { suggestion_id }),
  getImprovementReport: (window_days?: number) => {
    const qs = window_days !== undefined ? `?window_days=${window_days}` : ''
    return get<Record<string, unknown>>(`/learning/improvement-report${qs}`)
  },
}
