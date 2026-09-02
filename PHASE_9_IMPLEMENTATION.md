# Phase 9 — Query Logs and Query History Management
## Implementation Summary

### Overview
Phase 9 implements comprehensive Query Logs and Query History Management for the RAG platform. Every user query generates a structured record capturing query metadata, retrieval decisions, verification results, and performance metrics. The system provides role-based access control to ensure sensitive information is only visible to authorized users.

---

## Backend Implementation

### 1. Enhanced QueryLog Model
**File:** `backend/app/models/query_log.py`

The QueryLog ORM model now captures:
- **Query Identity:** `query_id`, `user_id`, `query_text`, `answer_text`
- **User Context:** `user_role`, `user_domain` (captured at query time)
- **Pipeline Decisions:** `intent`, `complexity`, `route`, `model_used`
- **Retrieval Details:**
  - `retrieval_strategy` - which retrieval method was used
  - `retrieved_chunk_ids` - all chunks retrieved (array)
  - `authorized_chunk_ids` - user-authorized subset (array)
  - `retrieval_score` - relevance score from retrieval
  - `reranking_score` - score after reranking
  - `reranking_explanation` - why reranking changed order
- **Outcome Signals:**
  - `confidence_score` - verification confidence (0-1)
  - `is_grounded` - whether answer is grounded in sources
  - `was_rewritten` - if answer was rewritten during verification
  - `hallucinations_detected` - count of hallucinations found
  - `citation_count` - number of citations in answer
  - `verification_result` - "verified", "partial", "unverified", "failed"
- **Ticket Association:** `ticket_id`, `ticket_status`
- **Sensitive Data:** `chunk_access_violations`, `access_violation_details`
- **Performance:** Latency breakdown (`retrieval_latency_ms`, `reranking_latency_ms`, `llm_latency_ms`)

### 2. Enhanced Query Log Schemas
**File:** `backend/app/schemas/query_log.py`

Three schema levels for different use cases:
- **QueryLogListItem:** Summary view for list pages (sensitive fields masked)
- **QueryLogDetail:** Complete trace with all fields for authorized users
- **QueryLogFilterParams:** Filter criteria for advanced searches
- **QueryLogListResponse:** Paginated list response
- **QueryLogDetailResponse:** Single query with authorization flag
- **QueryLogExportResponse:** Batch export response

### 3. Enhanced Query Log Service
**File:** `backend/app/services/query_log_service.py`

**Key Functions:**

```python
# Log a complete query with all Phase 9 fields
log_query(
    db, 
    query_id, 
    user_id, 
    user_role, 
    user_domain,
    query_text,
    answer_text,
    intent,
    complexity,
    route,
    retrieval_strategy,
    model_used,
    retrieved_chunk_ids,
    authorized_chunk_ids,
    retrieval_score,
    reranking_score,
    confidence_score,
    is_grounded,
    citation_count,
    verification_result,
    ticket_id,
    ticket_status,
    chunk_access_violations,
    latency_ms,
    # ... and individual latency breakdowns
)

# Get scoped query logs based on user permissions
get_query_logs_scoped(
    db,
    current_user,
    caller_role,
    skip,
    limit,
    filters  # Optional filter dict
)

# Check if user can view sensitive fields
can_view_sensitive_fields(caller_role, log_owner_id, current_user)
```

**Supported Filters:**
- `intent` - query intent
- `route` - retrieval route (vector/bm25/hybrid/graph)
- `retrieval_strategy` - retrieval method
- `model_used` - LLM model
- `user_role` - role at query time
- `user_domain` - organizational domain
- `min_confidence` / `max_confidence` - confidence range
- `ticket_status` - ticket status if created
- `verification_result` - verification outcome
- `is_grounded` / `was_rewritten` - boolean flags
- `date_from` / `date_to` - date range
- `search_text` - full-text search in query and answer

### 4. Comprehensive Query Log API Routes
**File:** `backend/app/api/query_logs.py`

#### Endpoints:

**GET `/api/v1/query-logs/`** - List query logs
```
Query Parameters:
  skip, limit - pagination
  intent, route, retrieval_strategy, model_used - exact filters
  user_role, user_domain - context filters
  min_confidence, max_confidence - range filters
  ticket_status, verification_result - status filters
  is_grounded, was_rewritten - boolean filters
  date_from, date_to - date range
  search_text - full-text search
  user_id - filter by specific user (scope permitting)

Response:
  {
    "total": 1234,
    "skip": 0,
    "limit": 50,
    "scope": "own|domain|global",
    "logs": [QueryLogListItem, ...]
  }
```

**GET `/api/v1/query-logs/{query_id}`** - Query log detail
```
Response:
  {
    "log": QueryLogDetail,
    "can_view_sensitive": boolean
  }
```

**GET `/api/v1/query-logs/export/all`** - Export query logs as JSON
```
Query Parameters: (same as list endpoint)
Limit: up to 10,000 records

Response:
  {
    "total_exported": 1500,
    "logs": [QueryLogDetail, ...]
  }
```

### 5. Role-Based Access Control (RBAC)

**Implemented Permission Checks:**

| Role | Permission | Access |
|------|-----------|--------|
| Employee | QUERY_LOG_VIEW_OWN | Own queries only |
| Analyst | QUERY_LOG_VIEW_DOMAIN | All domain queries + analytics |
| Domain Manager | QUERY_LOG_VIEW_DOMAIN | Domain queries + role-based filtering |
| Super Admin / Platform Owner | QUERY_LOG_VIEW_GLOBAL | All queries platform-wide |
| Any Role | QUERY_LOG_EXPORT | Export same scope as view permission |

**Sensitive Field Access:**
- Only users with QUERY_LOG_VIEW_DOMAIN or QUERY_LOG_VIEW_GLOBAL can view:
  - `chunk_access_violations`
  - `access_violation_details`
  - These fields are masked in responses to users with VIEW_OWN only

### 6. Query Logging Integration
**File:** `backend/app/api/rag.py`

The RAG query endpoint now:
1. Generates a unique `query_id` via `new_query_id()`
2. Measures execution time
3. Calls `log_query()` with comprehensive metadata after answer generation
4. Returns `query_id` in response for tracking

**Logged Information:**
- User identity and context (role, domain)
- Query analysis (intent, complexity, entities)
- Retrieval route and strategy
- All retrieved and authorized chunks
- Scores from retrieval and reranking
- Verification results and confidence
- Hallucinations detected
- Citations in answer
- Ticket creation if triggered
- Performance metrics (latency breakdown)

---

## Frontend Implementation

### 1. Enhanced TypeScript Types
**File:** `frontend/src/types/index.ts`

```typescript
interface QueryLogListItem {
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

interface QueryLogDetail extends QueryLogListItem {
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
```

### 2. Query Logs API Client
**File:** `frontend/src/lib/api.ts`

```typescript
const queryLogsApi = {
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
  }) => Promise<QueryLogListResponse>
  
  get: (queryId: string) => Promise<QueryLogDetailResponse>
  
  export: (opts?: {...}) => Promise<QueryLogExportResponse>
}
```

### 3. Query History Page (Main List View)
**File:** `frontend/src/app/(dashboard)/query-history/page.tsx`

**Features:**
- Real-time query log listing with pagination
- Search by query text or answer text
- Advanced filtering panel with:
  - Intent, route, model, verification status
  - Confidence range sliders
  - Ticket status, retrieval strategy
  - Date range picker (framework ready)
- Export to JSON with current filters applied
- Quick view with expandable details
- Performance metrics summary (total, verified, issues)
- Links to detailed view
- Loading and error states

**Key Components:**
- Search box with enter-to-search
- Collapsible advanced filters
- Statistics cards showing query metrics
- Query log cards with expandable details
- Pagination controls

### 4. Query Detail Page (Complete Trace View)
**File:** `frontend/src/app/(dashboard)/query-history/[queryId]/page.tsx`

**Displays:**
- Query and answer text
- Pipeline metadata (intent, route, model)
- Verification badges (verified/partial/unverified/failed)
- Performance metrics breakdown:
  - Total latency
  - Retrieval latency
  - Reranking latency
  - LLM latency
- Retrieval details:
  - Retrieved vs. authorized chunks
  - Retrieval and reranking scores
  - Strategy used
- Quality metrics:
  - Confidence score with visual bar
  - Hallucinations detected
  - Citation count
  - Grounding status
- Chunk information:
  - Retrieved chunk IDs
  - Authorized chunk IDs
- Verification details (if available)
- Reranking explanation
- Associated ticket information
- Sensitive fields (if authorized):
  - Access violation count
  - Access violation details
- Export to JSON
- Back navigation to list

---

## Database Schema Changes

### New Columns in `query_logs` Table

```sql
ALTER TABLE query_logs ADD COLUMN user_role VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN user_domain VARCHAR(256);
ALTER TABLE query_logs ADD COLUMN retrieval_strategy VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN retrieved_chunk_ids TEXT[] DEFAULT '{}';
ALTER TABLE query_logs ADD COLUMN authorized_chunk_ids TEXT[] DEFAULT '{}';
ALTER TABLE query_logs ADD COLUMN retrieval_score FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_score FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_explanation TEXT;
ALTER TABLE query_logs ADD COLUMN citation_count INTEGER DEFAULT 0;
ALTER TABLE query_logs ADD COLUMN verification_result VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN verification_details TEXT;
ALTER TABLE query_logs ADD COLUMN ticket_id UUID;
ALTER TABLE query_logs ADD COLUMN ticket_status VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN chunk_access_violations INTEGER DEFAULT 0;
ALTER TABLE query_logs ADD COLUMN access_violation_details TEXT;
ALTER TABLE query_logs ADD COLUMN retrieval_latency_ms FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_latency_ms FLOAT;
ALTER TABLE query_logs ADD COLUMN llm_latency_ms FLOAT;

-- Create indexes for common filters
CREATE INDEX idx_query_logs_user_role ON query_logs(user_role);
CREATE INDEX idx_query_logs_user_domain ON query_logs(user_domain);
CREATE INDEX idx_query_logs_retrieval_strategy ON query_logs(retrieval_strategy);
CREATE INDEX idx_query_logs_ticket_status ON query_logs(ticket_status);
CREATE INDEX idx_query_logs_verification_result ON query_logs(verification_result);
```

---

## Admin Panel Capabilities

### Query Logs List Page
✅ Search queries by text
✅ Filter by:
  - Intent (informational/navigational/transactional)
  - Retrieval route (vector/bm25/hybrid/graph)
  - LLM model
  - Verification result (verified/partial/unverified/failed)
  - Confidence range (0.0-1.0)
  - Ticket status (open/in_review/resolved)
  - Retrieval strategy
  - User role
  - Domain
  - Date range
✅ Pagination (skip/limit)
✅ Export filtered results to JSON
✅ Quick view with key metrics
✅ Link to detailed trace

### Query Detail Page
✅ Complete query trace
✅ Query and answer text
✅ Pipeline decisions
✅ Verification status
✅ Performance breakdown
✅ Retrieval details
✅ Quality metrics
✅ Chunk information
✅ Associated ticket
✅ Sensitive fields (with authorization check)
✅ Export individual query as JSON

---

## Security & Data Protection

### Sensitive Information Protection
1. **Access Violations Detail:** Only visible to admins/domain managers
2. **User Identification:** User IDs shown in list, full details in allowed scope
3. **Verification Details:** Technical details only for authorized roles
4. **Access Control:** Three-tier scoping:
   - OWN: User can only see own queries
   - DOMAIN: User can see their domain's queries
   - GLOBAL: Admin can see all queries

### Query Log Immutability
- Query logs are append-only (no updates/deletes via UI)
- Complete audit trail of all queries
- Query ID (QRY_xxx) serves as permanent reference

---

## Usage Examples

### Backend: Logging a Query
```python
from app.services.query_log_service import log_query, new_query_id

query_id = new_query_id()
log_query(
    db=db,
    query_id=query_id,
    user_id=str(current_user.id),
    user_role=caller_role.value,
    user_domain=current_user.department,
    query_text="What is the revenue from product X?",
    answer_text="Based on Q3 report, product X generated $2.3M...",
    intent="informational",
    complexity="moderate",
    route="vector",
    retrieval_strategy="adaptive",
    model_used="gpt-4",
    retrieved_chunk_ids=["doc1_chunk5", "doc2_chunk12"],
    authorized_chunk_ids=["doc1_chunk5", "doc2_chunk12"],
    retrieval_score=0.89,
    reranking_score=0.92,
    confidence_score=0.94,
    is_grounded=True,
    citation_count=2,
    verification_result="verified",
    latency_ms=2340,
    retrieval_latency_ms=800,
    llm_latency_ms=1400,
)
```

### Frontend: Fetching Query Logs
```typescript
// List with filters
const response = await queryLogsApi.list({
  skip: 0,
  limit: 50,
  intent: "informational",
  min_confidence: 0.8,
  max_confidence: 1.0,
  verification_result: "verified",
  date_from: "2024-01-01",
  date_to: "2024-01-31",
  search_text: "revenue",
})

// Get single query detail
const detail = await queryLogsApi.get("QRY_abc123def")

// Export filtered results
const export = await queryLogsApi.export({
  min_confidence: 0.9,
  limit: 5000,
})
```

---

## Testing Recommendations

### Backend Tests
- [ ] Test query logging with all parameter combinations
- [ ] Test role-based access scoping (own/domain/global)
- [ ] Test sensitive field masking
- [ ] Test filtering and searching functionality
- [ ] Test pagination with large result sets
- [ ] Test concurrent query logging (no race conditions)
- [ ] Test with null/missing fields (graceful degradation)

### Frontend Tests
- [ ] Test filter combinations
- [ ] Test pagination
- [ ] Test search functionality
- [ ] Test export JSON generation
- [ ] Test detail page navigation
- [ ] Test responsive design (mobile/tablet/desktop)
- [ ] Test error handling (network failures, 404s, etc.)
- [ ] Test permission-based field visibility

### Integration Tests
- [ ] End-to-end: Query → Log → View in History
- [ ] Verify query_id generation and uniqueness
- [ ] Verify all fields populated correctly
- [ ] Test role-based view permissions
- [ ] Test export data integrity

---

## Future Enhancements

1. **Analytics Dashboard:** Aggregate metrics by role, domain, intent, model
2. **Query Replay:** Re-run queries to compare answers over time
3. **Trend Analysis:** Hallucination rate trends, model performance trends
4. **Alerts:** Notify when hallucination rate exceeds threshold
5. **Query Categorization:** ML-based auto-categorization of common query types
6. **Performance Dashboards:** Latency tracking, SLA monitoring
7. **Advanced Export:** CSV, Parquet, streaming for large result sets
8. **Query Recommendations:** Suggest similar queries for reuse
9. **Feedback Integration:** Link queries to feedback ratings
10. **Performance Profiling:** Detailed timing breakdown per pipeline stage

---

## Conclusion

Phase 9 successfully implements comprehensive query logging and history management with:
- ✅ Complete query telemetry capture
- ✅ Role-based access control
- ✅ Rich filtering and search capabilities
- ✅ Detailed query trace views
- ✅ Sensitive data protection
- ✅ Export functionality
- ✅ Frontend admin panel

All queries are now fully tracked, searchable, and analyzable through a secure, permission-aware interface.
