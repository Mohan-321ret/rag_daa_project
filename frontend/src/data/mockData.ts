import type { Document, KnowledgeSource, QueryLog, SystemMetric, User, KnowledgeNode, VersionHistory, FeedbackEntry, AuditLog } from '@/types'

const depts = ['Engineering', 'Finance', 'Legal', 'HR', 'Marketing', 'Sales', 'Product', 'Procurement', 'Customer Success', 'Executive']
const authors = ['Sarah Chen', 'Marcus Johnson', 'Priya Patel', 'David Kim', 'Alex Rivera', 'Emma Wilson', 'James Liu', 'Lisa Thompson', 'Ryan Park', 'Nina Okafor', 'Carlos Mendez', 'Hans Mueller', 'Yuki Tanaka', 'Aisha Obi', 'Tom Bradley']
const langs = ['en', 'en', 'en', 'en', 'en', 'en', 'es', 'de', 'fr', 'zh']
const types: Document['type'][] = ['pdf', 'docx', 'xlsx', 'html', 'txt', 'email']
const statuses: Document['status'][] = ['completed', 'completed', 'completed', 'completed', 'processing', 'queued', 'failed']
const docNames = [
  'Q4 Financial Report 2024', 'Product Roadmap H1 2025', 'Customer Satisfaction Survey', 'Legal Compliance Framework',
  'Engineering Architecture Docs', 'HR Policy Manual 2024', 'Market Analysis Report', 'Vendor Contracts 2024',
  'Technical Specification v3', 'Sales Performance Dashboard', 'Informe Anual 2024', 'Technische Dokumentation',
  'Board Meeting Minutes Q4', 'Security Audit Report', 'API Integration Guide', 'Data Governance Policy',
  'Employee Handbook 2024', 'Budget Forecast 2025', 'Competitive Intelligence Brief', 'Customer Onboarding Guide',
  'Infrastructure Runbook', 'Privacy Impact Assessment', 'SOC2 Compliance Report', 'Incident Response Plan',
  'Knowledge Management Strategy', 'AI Ethics Guidelines', 'Cloud Migration Plan', 'DevOps Playbook',
  'Revenue Recognition Policy', 'Supply Chain Analysis', 'Brand Guidelines 2024', 'Partnership Agreement Template',
  'Risk Assessment Matrix', 'Quarterly Business Review', 'Product Requirements Document', 'UX Research Findings',
  'Database Schema Documentation', 'Deployment Checklist', 'Disaster Recovery Plan', 'Training Materials v2',
]

function rnd(min: number, max: number) { return Math.floor(Math.random() * (max - min + 1)) + min }
function pick<T>(arr: T[]): T { return arr[Math.floor(Math.random() * arr.length)] }

export const mockDocuments: Document[] = Array.from({ length: 120 }, (_, i) => {
  const type = pick(types)
  const status = pick(statuses)
  const lang = pick(langs)
  const done = status === 'completed'
  const chunks = done ? rnd(40, 350) : 0
  const name = i < docNames.length ? docNames[i] : `Document ${i + 1}`
  const ext = type === 'html' ? 'html' : type === 'txt' ? 'txt' : type === 'email' ? 'eml' : type
  return {
    id: `d${i + 1}`,
    name: `${name}.${ext}`,
    type,
    size: rnd(200000, 12000000),
    status,
    department: pick(depts),
    author: pick(authors),
    uploadedAt: new Date(Date.now() - rnd(0, 30) * 86400000 - rnd(0, 86400000)).toISOString(),
    version: rnd(1, 8),
    language: lang,
    chunkCount: chunks,
    embeddingCount: chunks,
    ocrStatus: type === 'pdf' ? (done ? 'completed' : status === 'processing' ? 'pending' : 'not_required') : 'not_required',
    tags: [pick(['finance', 'legal', 'technical', 'hr', 'product', 'sales', 'marketing', 'compliance', 'security', 'operations'])],
    permissions: [pick(depts).toLowerCase(), 'executive'],
    confidenceScore: done ? parseFloat((0.75 + Math.random() * 0.24).toFixed(2)) : 0,
  }
})

// Keep first 12 as fixed realistic ones
mockDocuments[0] = { id: 'd1', name: 'Q4 Financial Report 2024.pdf', type: 'pdf', size: 4200000, status: 'completed', department: 'Finance', author: 'Sarah Chen', uploadedAt: '2024-12-15T09:23:00Z', version: 3, language: 'en', chunkCount: 142, embeddingCount: 142, ocrStatus: 'completed', tags: ['finance', 'quarterly', 'report'], permissions: ['finance', 'executive'], confidenceScore: 0.97 }
mockDocuments[1] = { id: 'd2', name: 'Product Roadmap H1 2025.docx', type: 'docx', size: 1800000, status: 'completed', department: 'Product', author: 'Marcus Johnson', uploadedAt: '2024-12-14T14:10:00Z', version: 5, language: 'en', chunkCount: 89, embeddingCount: 89, ocrStatus: 'not_required', tags: ['product', 'roadmap', 'strategy'], permissions: ['product', 'engineering', 'executive'], confidenceScore: 0.94 }
mockDocuments[2] = { id: 'd3', name: 'Customer Satisfaction Survey.xlsx', type: 'xlsx', size: 890000, status: 'completed', department: 'Customer Success', author: 'Priya Patel', uploadedAt: '2024-12-13T11:45:00Z', version: 1, language: 'en', chunkCount: 56, embeddingCount: 56, ocrStatus: 'not_required', tags: ['customer', 'survey', 'satisfaction'], permissions: ['cs', 'product', 'executive'], confidenceScore: 0.91 }
mockDocuments[3] = { id: 'd4', name: 'Legal Compliance Framework.pdf', type: 'pdf', size: 6700000, status: 'processing', department: 'Legal', author: 'David Kim', uploadedAt: '2024-12-15T16:30:00Z', version: 2, language: 'en', chunkCount: 0, embeddingCount: 0, ocrStatus: 'pending', tags: ['legal', 'compliance', 'framework'], permissions: ['legal', 'executive'], confidenceScore: 0 }

export const mockKnowledgeSources: KnowledgeSource[] = [
  { id: 'ks1', name: 'SharePoint Enterprise', type: 'file_system', status: 'active', documentCount: 4821, lastSync: '2024-12-15T18:00:00Z', department: 'All' },
  { id: 'ks2', name: 'Salesforce CRM', type: 'api', status: 'active', documentCount: 12450, lastSync: '2024-12-15T17:30:00Z', department: 'Sales' },
  { id: 'ks3', name: 'Confluence Wiki', type: 'web', status: 'syncing', documentCount: 3200, lastSync: '2024-12-15T16:00:00Z', department: 'Engineering' },
  { id: 'ks4', name: 'Exchange Email Archive', type: 'email', status: 'active', documentCount: 89000, lastSync: '2024-12-15T18:00:00Z', department: 'All' },
  { id: 'ks5', name: 'PostgreSQL Data Warehouse', type: 'database', status: 'active', documentCount: 234000, lastSync: '2024-12-15T17:45:00Z', department: 'Finance' },
  { id: 'ks6', name: 'GitHub Repositories', type: 'api', status: 'inactive', documentCount: 1890, lastSync: '2024-12-14T12:00:00Z', department: 'Engineering' },
]

export const mockQueryLogs: QueryLog[] = [
  { id: 'q1', query: 'What were the key financial highlights from Q4 2024?', intent: 'information_retrieval', entities: ['Q4 2024', 'financial highlights'], complexity: 'moderate', retrievalMethod: 'hybrid', confidence: 0.94, latency: 1240, timestamp: '2024-12-15T18:45:00Z', sources: ['d1', 'd7'], hallucination: false, userId: 'u1' },
  { id: 'q2', query: 'Summarize the product roadmap for H1 2025', intent: 'summarization', entities: ['product roadmap', 'H1 2025'], complexity: 'simple', retrievalMethod: 'vector', confidence: 0.97, latency: 890, timestamp: '2024-12-15T18:30:00Z', sources: ['d2'], hallucination: false, userId: 'u2' },
  { id: 'q3', query: 'What are the compliance requirements for data handling?', intent: 'information_retrieval', entities: ['compliance', 'data handling'], complexity: 'complex', retrievalMethod: 'graph', confidence: 0.78, latency: 2100, timestamp: '2024-12-15T18:15:00Z', sources: ['d4', 'd6'], hallucination: false, userId: 'u3' },
  { id: 'q4', query: 'Compare customer satisfaction scores across departments', intent: 'comparison', entities: ['customer satisfaction', 'departments'], complexity: 'complex', retrievalMethod: 'hybrid', confidence: 0.85, latency: 1890, timestamp: '2024-12-15T18:00:00Z', sources: ['d3', 'd7'], hallucination: false, userId: 'u1' },
  { id: 'q5', query: 'What is the current API rate limit for the payment service?', intent: 'factual_lookup', entities: ['API rate limit', 'payment service'], complexity: 'simple', retrievalMethod: 'bm25', confidence: 0.62, latency: 450, timestamp: '2024-12-15T17:45:00Z', sources: ['d9'], hallucination: true, userId: 'u4' },
  { id: 'q6', query: 'List all active vendor contracts expiring in Q1 2025', intent: 'listing', entities: ['vendor contracts', 'Q1 2025'], complexity: 'moderate', retrievalMethod: 'hybrid', confidence: 0.88, latency: 1560, timestamp: '2024-12-15T17:30:00Z', sources: ['d8'], hallucination: false, userId: 'u2' },
  { id: 'q7', query: 'What is the EBITDA margin trend over the last 4 quarters?', intent: 'trend_analysis', entities: ['EBITDA', 'margin', 'quarters'], complexity: 'complex', retrievalMethod: 'hybrid', confidence: 0.91, latency: 1780, timestamp: '2024-12-15T17:00:00Z', sources: ['d1'], hallucination: false, userId: 'u1' },
  { id: 'q8', query: 'Summarize the key risks identified in the security audit', intent: 'summarization', entities: ['security audit', 'risks'], complexity: 'moderate', retrievalMethod: 'vector', confidence: 0.89, latency: 1120, timestamp: '2024-12-15T16:30:00Z', sources: ['d14'], hallucination: false, userId: 'u5' },
  { id: 'q9', query: 'What are the onboarding steps for new enterprise customers?', intent: 'procedural', entities: ['onboarding', 'enterprise customers'], complexity: 'simple', retrievalMethod: 'bm25', confidence: 0.93, latency: 670, timestamp: '2024-12-15T16:00:00Z', sources: ['d20'], hallucination: false, userId: 'u3' },
  { id: 'q10', query: 'How does our cloud infrastructure compare to industry benchmarks?', intent: 'comparison', entities: ['cloud infrastructure', 'benchmarks'], complexity: 'complex', retrievalMethod: 'graph', confidence: 0.71, latency: 2340, timestamp: '2024-12-15T15:30:00Z', sources: ['d27'], hallucination: false, userId: 'u2' },
]

export const mockSystemMetrics: SystemMetric[] = Array.from({ length: 24 }, (_, i) => ({
  timestamp: new Date(Date.now() - (23 - i) * 3600000).toISOString(),
  cpu: 30 + Math.random() * 40,
  memory: 45 + Math.random() * 30,
  storage: 62 + Math.random() * 5,
  embeddingQueue: Math.floor(Math.random() * 50),
  activeJobs: Math.floor(Math.random() * 12),
  errors: Math.floor(Math.random() * 3),
}))

export const mockUsers: User[] = [
  { id: 'u1', name: 'Sarah Chen', email: 'sarah.chen@enterprise.com', role: 'admin', department: 'Engineering', lastActive: '2024-12-15T18:50:00Z' },
  { id: 'u2', name: 'Marcus Johnson', email: 'marcus.j@enterprise.com', role: 'analyst', department: 'Product', lastActive: '2024-12-15T18:30:00Z' },
  { id: 'u3', name: 'Priya Patel', email: 'priya.p@enterprise.com', role: 'analyst', department: 'Customer Success', lastActive: '2024-12-15T17:45:00Z' },
  { id: 'u4', name: 'David Kim', email: 'david.k@enterprise.com', role: 'viewer', department: 'Legal', lastActive: '2024-12-15T16:00:00Z' },
  { id: 'u5', name: 'Alex Rivera', email: 'alex.r@enterprise.com', role: 'engineer', department: 'Engineering', lastActive: '2024-12-15T18:55:00Z' },
  { id: 'u6', name: 'Emma Wilson', email: 'emma.w@enterprise.com', role: 'analyst', department: 'HR', lastActive: '2024-12-15T14:20:00Z' },
  { id: 'u7', name: 'James Liu', email: 'james.l@enterprise.com', role: 'viewer', department: 'Marketing', lastActive: '2024-12-15T12:00:00Z' },
]

export const mockKnowledgeNodes: KnowledgeNode[] = [
  { id: 'n1', label: 'Financial Performance', type: 'concept', connections: 24, weight: 0.92 },
  { id: 'n2', label: 'Q4 2024', type: 'entity', connections: 18, weight: 0.88 },
  { id: 'n3', label: 'Product Strategy', type: 'concept', connections: 31, weight: 0.95 },
  { id: 'n4', label: 'Compliance Framework', type: 'document', connections: 12, weight: 0.79 },
  { id: 'n5', label: 'Customer Satisfaction', type: 'concept', connections: 22, weight: 0.87 },
  { id: 'n6', label: 'API Architecture', type: 'concept', connections: 45, weight: 0.98 },
  { id: 'n7', label: 'Revenue Growth', type: 'entity', connections: 16, weight: 0.84 },
  { id: 'n8', label: 'Market Analysis', type: 'document', connections: 28, weight: 0.91 },
  { id: 'n9', label: 'Security Governance', type: 'concept', connections: 19, weight: 0.86 },
  { id: 'n10', label: 'Cloud Infrastructure', type: 'concept', connections: 37, weight: 0.93 },
  { id: 'n11', label: 'Employee Policies', type: 'document', connections: 14, weight: 0.81 },
  { id: 'n12', label: 'Vendor Management', type: 'concept', connections: 11, weight: 0.76 },
]

export const mockVersionHistory: VersionHistory[] = [
  { version: 8, timestamp: '2024-12-15T18:00:00Z', author: 'Sarah Chen', changes: 'Added 47 new documents, updated 12 embeddings, resolved 2 conflicts', documentCount: 4821, status: 'current' },
  { version: 7, timestamp: '2024-12-14T12:00:00Z', author: 'Alex Rivera', changes: 'Reindexed engineering docs, fixed 3 conflicts, updated graph edges', documentCount: 4774, status: 'stable' },
  { version: 6, timestamp: '2024-12-13T09:00:00Z', author: 'Marcus Johnson', changes: 'Added product roadmap documents, refreshed embeddings for 89 chunks', documentCount: 4720, status: 'stable' },
  { version: 5, timestamp: '2024-12-12T15:00:00Z', author: 'Sarah Chen', changes: 'Bulk import from SharePoint (312 documents), language detection pass', documentCount: 4650, status: 'stable' },
  { version: 4, timestamp: '2024-12-10T11:00:00Z', author: 'Priya Patel', changes: 'Customer survey data integration, updated satisfaction metrics', documentCount: 4580, status: 'deprecated' },
  { version: 3, timestamp: '2024-12-08T09:00:00Z', author: 'David Kim', changes: 'Legal document batch, compliance framework v2 added', documentCount: 4420, status: 'deprecated' },
]

export const mockFeedback: FeedbackEntry[] = [
  { id: 'f1', queryId: 'q1', rating: 5, comment: 'Excellent accuracy, very relevant sources cited', timestamp: '2024-12-15T18:50:00Z', userId: 'u1', category: 'accuracy' },
  { id: 'f2', queryId: 'q2', rating: 4, comment: 'Good summary but missed some key milestones', timestamp: '2024-12-15T18:35:00Z', userId: 'u2', category: 'completeness' },
  { id: 'f3', queryId: 'q3', rating: 3, comment: 'Response was slow and partially incorrect on retention period', timestamp: '2024-12-15T18:20:00Z', userId: 'u3', category: 'accuracy' },
  { id: 'f4', queryId: 'q5', rating: 2, comment: 'Hallucinated API limits, needs improvement urgently', timestamp: '2024-12-15T17:50:00Z', userId: 'u4', category: 'accuracy' },
  { id: 'f5', queryId: 'q7', rating: 5, comment: 'Perfect trend analysis with correct chart data', timestamp: '2024-12-15T17:10:00Z', userId: 'u1', category: 'relevance' },
  { id: 'f6', queryId: 'q8', rating: 4, comment: 'Good coverage of risks, could include remediation steps', timestamp: '2024-12-15T16:40:00Z', userId: 'u5', category: 'completeness' },
]

export const mockAuditLogs: AuditLog[] = [
  { id: 'a1', action: 'DOCUMENT_UPLOAD', userId: 'u1', resource: 'Q4 Financial Report 2024.pdf', timestamp: '2024-12-15T09:23:00Z', ip: '192.168.1.45', status: 'success' },
  { id: 'a2', action: 'QUERY_EXECUTED', userId: 'u2', resource: 'Query Engine', timestamp: '2024-12-15T18:30:00Z', ip: '192.168.1.67', status: 'success' },
  { id: 'a3', action: 'PERMISSION_CHANGE', userId: 'u1', resource: 'Legal Compliance Framework.pdf', timestamp: '2024-12-15T16:45:00Z', ip: '192.168.1.45', status: 'success' },
  { id: 'a4', action: 'LOGIN_ATTEMPT', userId: 'unknown', resource: 'Auth Service', timestamp: '2024-12-15T14:22:00Z', ip: '203.45.67.89', status: 'failed' },
  { id: 'a5', action: 'KNOWLEDGE_ROLLBACK', userId: 'u1', resource: 'Knowledge Base v7', timestamp: '2024-12-14T12:30:00Z', ip: '192.168.1.45', status: 'success' },
  { id: 'a6', action: 'API_KEY_GENERATED', userId: 'u5', resource: 'API Management', timestamp: '2024-12-14T10:00:00Z', ip: '192.168.1.89', status: 'success' },
  { id: 'a7', action: 'BULK_EXPORT', userId: 'u2', resource: 'Knowledge Repository', timestamp: '2024-12-13T15:00:00Z', ip: '192.168.1.67', status: 'success' },
  { id: 'a8', action: 'MODEL_CONFIG_CHANGE', userId: 'u1', resource: 'LLM Settings', timestamp: '2024-12-13T11:00:00Z', ip: '192.168.1.45', status: 'success' },
  { id: 'a9', action: 'USER_ROLE_CHANGE', userId: 'u1', resource: 'User: u6', timestamp: '2024-12-12T09:00:00Z', ip: '192.168.1.45', status: 'success' },
  { id: 'a10', action: 'FAILED_UPLOAD', userId: 'u7', resource: 'Vendor Contracts 2024.pdf', timestamp: '2024-12-15T17:00:00Z', ip: '192.168.1.102', status: 'failed' },
]

export const dashboardStats = {
  totalDocuments: 4821,
  knowledgeSources: 6,
  versions: 8,
  vectorCount: 847293,
  graphNodes: 12847,
  activeUsers: 47,
  queriesToday: 1284,
  avgRetrievalTime: 1.24,
  confidenceScore: 0.91,
  hallucinationRate: 0.034,
  systemHealth: 98.7,
}

export const queryVolumeData = Array.from({ length: 30 }, (_, i) => ({
  name: `Dec ${i + 1}`,
  queries: Math.floor(800 + Math.random() * 600),
  successful: Math.floor(750 + Math.random() * 550),
}))

export const retrievalMethodData = [
  { name: 'Hybrid', value: 45, color: '#6366f1' },
  { name: 'Vector', value: 30, color: '#3b82f6' },
  { name: 'BM25', value: 15, color: '#06b6d4' },
  { name: 'Graph', value: 10, color: '#8b5cf6' },
]

export const confidenceOverTime = Array.from({ length: 14 }, (_, i) => ({
  name: `Dec ${i + 2}`,
  confidence: 0.82 + Math.random() * 0.12,
  hallucination: 0.02 + Math.random() * 0.04,
}))

export const departmentDocuments = [
  { name: 'Engineering', value: 1240, color: '#3b82f6' },
  { name: 'Finance', value: 890, color: '#10b981' },
  { name: 'Legal', value: 670, color: '#f59e0b' },
  { name: 'HR', value: 540, color: '#8b5cf6' },
  { name: 'Marketing', value: 480, color: '#ec4899' },
  { name: 'Sales', value: 420, color: '#06b6d4' },
  { name: 'Product', value: 380, color: '#f97316' },
  { name: 'Other', value: 201, color: '#6b7280' },
]

export const latencyTrendData = Array.from({ length: 14 }, (_, i) => ({
  name: `Dec ${i + 2}`,
  vector: 400 + Math.random() * 200,
  bm25: 150 + Math.random() * 100,
  graph: 600 + Math.random() * 300,
  hybrid: 800 + Math.random() * 400,
}))

export const learningKpiData = Array.from({ length: 12 }, (_, i) => ({
  month: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][i],
  accuracy: 0.72 + i * 0.018 + Math.random() * 0.01,
  relevance: 0.68 + i * 0.02 + Math.random() * 0.01,
  speed: 0.65 + i * 0.022 + Math.random() * 0.01,
}))
