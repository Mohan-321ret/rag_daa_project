export interface Document {
  id: string
  name: string
  type: 'pdf' | 'docx' | 'xlsx' | 'html' | 'txt' | 'email'
  size: number
  status: 'processing' | 'completed' | 'failed' | 'queued'
  department: string
  author: string
  uploadedAt: string
  version: number
  language: string
  chunkCount: number
  embeddingCount: number
  ocrStatus: 'pending' | 'completed' | 'not_required'
  tags: string[]
  permissions: string[]
  confidenceScore: number
}

export interface KnowledgeSource {
  id: string
  name: string
  type: 'database' | 'api' | 'file_system' | 'web' | 'email'
  status: 'active' | 'inactive' | 'syncing'
  documentCount: number
  lastSync: string
  department: string
}

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

export interface QueryLog {
  id: string
  query: string
  intent: string
  entities: string[]
  complexity: 'simple' | 'moderate' | 'complex'
  retrievalMethod: string
  confidence: number
  latency: number
  timestamp: string
  sources: string[]
  hallucination: boolean
  userId: string
}

export interface SystemMetric {
  timestamp: string
  cpu: number
  memory: number
  storage: number
  embeddingQueue: number
  activeJobs: number
  errors: number
}

export interface User {
  id: string
  name: string
  email: string
  role: 'admin' | 'analyst' | 'viewer' | 'engineer'
  department: string
  lastActive: string
  avatar?: string
}

export interface KnowledgeNode {
  id: string
  label: string
  type: 'concept' | 'entity' | 'document' | 'relation'
  connections: number
  weight: number
}

export interface VersionHistory {
  version: number
  timestamp: string
  author: string
  changes: string
  documentCount: number
  status: 'stable' | 'deprecated' | 'current'
}

export interface RetrievalResult {
  id: string
  content: string
  source: string
  score: number
  method: 'vector' | 'bm25' | 'graph' | 'hybrid'
  chunkIndex: number
}

export interface Claim {
  id: string
  text: string
  confidence: number
  verified: boolean
  evidence: string[]
  hallucination: boolean
}

export interface FeedbackEntry {
  id: string
  queryId: string
  rating: 1 | 2 | 3 | 4 | 5
  comment: string
  timestamp: string
  userId: string
  category: 'accuracy' | 'relevance' | 'completeness' | 'speed'
}

export interface AuditLog {
  id: string
  action: string
  userId: string
  resource: string
  timestamp: string
  ip: string
  status: 'success' | 'failed' | 'warning'
}

export interface NavItem {
  label: string
  href: string
  icon: string
  badge?: number
  children?: NavItem[]
}

export interface ChartDataPoint {
  name: string
  value: number
  [key: string]: string | number
}
