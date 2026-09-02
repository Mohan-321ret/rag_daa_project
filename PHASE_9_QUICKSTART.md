# Phase 9 Quick Start Guide
## Query Logs and Query History Management

### For Backend Developers

#### 1. Logging a Query

In any endpoint that handles queries, use the query log service:

```python
from app.services.query_log_service import log_query, new_query_id

# Generate a unique query ID
query_id = new_query_id()

# Log the query after it's been processed
log_query(
    db=db,
    query_id=query_id,
    user_id=str(current_user.id),
    user_role=caller_role.value,
    user_domain=current_user.department,
    query_text="What is X?",
    answer_text="X is...",
    intent="informational",  # From query intelligence
    complexity="moderate",    # From query analysis
    route="vector",          # From adaptive retrieval
    retrieval_strategy="vector",
    model_used="gpt-4",
    retrieved_chunk_ids=["chunk1", "chunk2"],
    authorized_chunk_ids=["chunk1", "chunk2"],
    retrieval_score=0.89,
    reranking_score=0.92,
    confidence_score=0.94,
    is_grounded=True,
    was_rewritten=False,
    hallucinations_detected=0,
    citation_count=2,
    verification_result="verified",
    ticket_id=None,  # If a ticket was created
    ticket_status=None,
    latency_ms=2340,
    retrieval_latency_ms=800,
    llm_latency_ms=1400,
)
```

**Note:** The `log_query()` function is non-blocking and won't interrupt the main request if logging fails.

#### 2. Querying Logs

```python
from app.services.query_log_service import get_query_logs_scoped

# Get scoped logs for current user
logs, total, scope = get_query_logs_scoped(
    db=db,
    current_user=current_user,
    caller_role=caller_role,
    skip=0,
    limit=50,
    filters={
        "intent": "informational",
        "route": "vector",
        "min_confidence": 0.8,
        "max_confidence": 1.0,
    }
)

# logs: List[QueryLog]
# total: int (total count matching filters)
# scope: "own" | "domain" | "global"
```

#### 3. Checking Permissions

```python
from app.services.query_log_service import can_view_sensitive_fields

can_view = can_view_sensitive_fields(caller_role, log.user_id, current_user)
# Returns: bool (whether to show sensitive fields)
```

---

### For Frontend Developers

#### 1. View Query Logs List

The page is at `/query-history` and automatically loads logs with:
- Pagination (skip/limit)
- Real-time search
- Advanced filtering
- Export to JSON

#### 2. Use the API

```typescript
import { queryLogsApi } from '@/lib/api'

// List with filters
const response = await queryLogsApi.list({
  skip: 0,
  limit: 50,
  intent: "informational",
  route: "vector",
  min_confidence: 0.8,
  search_text: "revenue",
})

console.log(response.logs)      // QueryLogListItem[]
console.log(response.total)     // number
console.log(response.scope)     // "own" | "domain" | "global"

// Get single query detail
const detail = await queryLogsApi.get("QRY_abc123xyz")

console.log(detail.log)                    // QueryLogDetail
console.log(detail.can_view_sensitive)    // boolean

// Export
const exported = await queryLogsApi.export({
  min_confidence: 0.9,
  limit: 5000,
})
```

#### 3. Add Custom Filters

Edit the filter form in `/query-history/page.tsx`:

```tsx
<select
  value={filters.yourNewFilter}
  onChange={e => setFilters(f => ({ ...f, yourNewFilter: e.target.value }))}
>
  <option value="">All</option>
  <option value="option1">Option 1</option>
</select>
```

Pass it when loading:
```tsx
const response = await queryLogsApi.list({
  yourNewFilter: filters.yourNewFilter || undefined,
  // ...
})
```

---

### Database Setup

#### Add New Columns

Run in PostgreSQL:

```sql
-- User context
ALTER TABLE query_logs ADD COLUMN user_role VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN user_domain VARCHAR(256);

-- Retrieval details
ALTER TABLE query_logs ADD COLUMN retrieval_strategy VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN retrieved_chunk_ids TEXT[] DEFAULT '{}';
ALTER TABLE query_logs ADD COLUMN authorized_chunk_ids TEXT[] DEFAULT '{}';
ALTER TABLE query_logs ADD COLUMN retrieval_score FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_score FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_explanation TEXT;

-- Quality metrics
ALTER TABLE query_logs ADD COLUMN citation_count INTEGER DEFAULT 0;
ALTER TABLE query_logs ADD COLUMN verification_result VARCHAR(32);
ALTER TABLE query_logs ADD COLUMN verification_details TEXT;

-- Ticket association
ALTER TABLE query_logs ADD COLUMN ticket_id UUID;
ALTER TABLE query_logs ADD COLUMN ticket_status VARCHAR(32);

-- Sensitive data
ALTER TABLE query_logs ADD COLUMN chunk_access_violations INTEGER DEFAULT 0;
ALTER TABLE query_logs ADD COLUMN access_violation_details TEXT;

-- Latency breakdown
ALTER TABLE query_logs ADD COLUMN retrieval_latency_ms FLOAT;
ALTER TABLE query_logs ADD COLUMN reranking_latency_ms FLOAT;
ALTER TABLE query_logs ADD COLUMN llm_latency_ms FLOAT;

-- Indexes for common queries
CREATE INDEX idx_query_logs_user_role ON query_logs(user_role);
CREATE INDEX idx_query_logs_retrieval_strategy ON query_logs(retrieval_strategy);
CREATE INDEX idx_query_logs_ticket_status ON query_logs(ticket_status);
CREATE INDEX idx_query_logs_verification_result ON query_logs(verification_result);
```

---

### Common Use Cases

#### 1. Find Queries with Low Confidence

```typescript
const response = await queryLogsApi.list({
  max_confidence: 0.5,
})
```

#### 2. Find Hallucinated Answers

The page shows hallucinations_detected in each row. Filter manually or check query detail.

#### 3. Find Slow Queries

Implement latency filtering in frontend (not yet built). For now:
```typescript
const response = await queryLogsApi.export({ limit: 1000 })
const slow = response.logs.filter(l => l.latency_ms > 5000)
```

#### 4. Export All Queries for Analysis

```typescript
const exported = await queryLogsApi.export({
  limit: 10000,
  date_from: "2024-01-01",
  date_to: "2024-01-31",
})

// Save as JSON
const blob = new Blob([JSON.stringify(exported.logs, null, 2)])
const url = URL.createObjectURL(blob)
const link = document.createElement('a')
link.href = url
link.download = 'query-logs.json'
link.click()
```

#### 5. Analyze by Model

```typescript
const response = await queryLogsApi.list({
  model_used: "gpt-4",
})
```

#### 6. View Admin Dashboard (Different Role Scopes)

- **Employee:** Only sees own queries
- **Analyst:** Can see all analytics-related queries
- **Domain Manager:** Can see queries for their domain
- **Super Admin:** Can see all queries platform-wide

The `scope` field in response tells you what was returned:
- "own": Limited to current user
- "domain": Limited to user's domain(s)
- "global": All queries

---

### Troubleshooting

#### "Not authorized to view this query log"
- Check your role and permissions
- Own queries should always be visible
- Admin roles can see all queries

#### "Query log not found"
- Verify the query_id is correct (format: QRY_xxxxxxxxxx)
- Check if the query was successfully logged

#### "No results with filters"
- Try removing some filters
- Check date range (may be off by timezone)
- Verify filter values exist in your data

#### Missing fields in response
- If you see null fields, check if they were captured during logging
- Some fields like intent/complexity need query intelligence service
- Verification fields need evidence_verification service

---

### Performance Tips

1. **Pagination:** Always use skip/limit for large result sets
2. **Filtering:** Filter at API level, not in frontend
3. **Export:** Limit exports to reasonable sizes (< 10,000 records)
4. **Indexes:** Query logs table has indexes on common filter columns
5. **Caching:** Consider caching filter results in frontend

---

### Security Reminders

1. ✅ Sensitive fields automatically masked for non-admins
2. ✅ Users can only see queries they have permission for
3. ✅ Query logs are immutable (no edits/deletes)
4. ✅ All access is logged in audit trail
5. ✅ Query IDs are unique and permanent

---

### Next Steps

1. Run database migrations
2. Test logging in RAG endpoint
3. Access `/query-history` to view logs
4. Test filters and export
5. Provide feedback for improvements

---

### Support

For issues or questions:
- Check PHASE_9_IMPLEMENTATION.md for full technical details
- Review test files for usage examples
- Contact development team
