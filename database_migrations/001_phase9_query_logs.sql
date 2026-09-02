-- Phase 9 Database Migration Script
-- Query Logs and Query History Management
-- 
-- This script adds all necessary columns to support Phase 9 features.
-- Run this against your PostgreSQL database after deploying Phase 9 code.

-- ============================================================================
-- SECTION 1: User Context Columns
-- ============================================================================

-- Store the user's role at the time of query
-- Allows for role-based analytics even if user role changes later
ALTER TABLE query_logs 
ADD COLUMN user_role VARCHAR(32);

CREATE INDEX idx_query_logs_user_role ON query_logs(user_role);

-- Store the user's organizational domain
-- Enables domain-scoped filtering and analytics
ALTER TABLE query_logs 
ADD COLUMN user_domain VARCHAR(256);

CREATE INDEX idx_query_logs_user_domain ON query_logs(user_domain);

-- ============================================================================
-- SECTION 2: Retrieval Strategy & Chunk Information
-- ============================================================================

-- Which retrieval strategy was used (vector, bm25, adaptive, etc.)
ALTER TABLE query_logs 
ADD COLUMN retrieval_strategy VARCHAR(32);

CREATE INDEX idx_query_logs_retrieval_strategy ON query_logs(retrieval_strategy);

-- All chunk IDs that were retrieved before filtering
-- Stored as PostgreSQL array for efficient querying
ALTER TABLE query_logs 
ADD COLUMN retrieved_chunk_ids TEXT[] DEFAULT '{}';

-- Chunk IDs that the user was authorized to see
-- Allows tracking of access control filtering
ALTER TABLE query_logs 
ADD COLUMN authorized_chunk_ids TEXT[] DEFAULT '{}';

-- Relevance score from the initial retrieval
-- Range: 0.0 - 1.0, higher is better
ALTER TABLE query_logs 
ADD COLUMN retrieval_score FLOAT;

-- Score after reranking (if applied)
-- Allows comparison of retrieval vs reranking effectiveness
ALTER TABLE query_logs 
ADD COLUMN reranking_score FLOAT;

-- Explanation of why reranking changed order
-- Text field for storing reasoning from reranker
ALTER TABLE query_logs 
ADD COLUMN reranking_explanation TEXT;

-- ============================================================================
-- SECTION 3: Quality & Verification Metrics
-- ============================================================================

-- Number of citations in the final answer
-- Helps track grounding quality
ALTER TABLE query_logs 
ADD COLUMN citation_count INTEGER DEFAULT 0;

-- Verification result: verified, partial, unverified, failed
-- Indicates the confidence in the answer
ALTER TABLE query_logs 
ADD COLUMN verification_result VARCHAR(32);

CREATE INDEX idx_query_logs_verification_result ON query_logs(verification_result);

-- Detailed explanation of verification outcome
-- Text field for storing verification reasoning
ALTER TABLE query_logs 
ADD COLUMN verification_details TEXT;

-- ============================================================================
-- SECTION 4: Ticket Association (Review Ticketing System)
-- ============================================================================

-- Link to ticket if one was created for this query
-- Foreign key reference to tickets table
ALTER TABLE query_logs 
ADD COLUMN ticket_id UUID;

-- Status of the ticket at the time of logging
-- Allows tracking ticket progression
ALTER TABLE query_logs 
ADD COLUMN ticket_status VARCHAR(32);

CREATE INDEX idx_query_logs_ticket_status ON query_logs(ticket_status);

-- ============================================================================
-- SECTION 5: Sensitive Data (Access Control Violations)
-- ============================================================================

-- Count of chunks that violated access control
-- Helps track security issues
ALTER TABLE query_logs 
ADD COLUMN chunk_access_violations INTEGER DEFAULT 0;

-- Details about which chunks violated access control
-- SENSITIVE: Only visible to admins
-- Contains chunk IDs and violation reasons
ALTER TABLE query_logs 
ADD COLUMN access_violation_details TEXT;

-- ============================================================================
-- SECTION 6: Performance Latency Breakdown
-- ============================================================================

-- Latency spent on retrieval phase (ms)
-- Helps identify retrieval bottlenecks
ALTER TABLE query_logs 
ADD COLUMN retrieval_latency_ms FLOAT;

-- Latency spent on reranking phase (ms)
-- Helps identify reranking overhead
ALTER TABLE query_logs 
ADD COLUMN reranking_latency_ms FLOAT;

-- Latency spent on LLM generation phase (ms)
-- Helps identify LLM bottlenecks
ALTER TABLE query_logs 
ADD COLUMN llm_latency_ms FLOAT;

-- ============================================================================
-- SECTION 7: Create Additional Indexes for Query Performance
-- ============================================================================

-- These indexes optimize the most common filter queries

-- Combination index for user_id + created_at (own query history)
CREATE INDEX idx_query_logs_user_created ON query_logs(user_id, created_at DESC);

-- Indexes for common filtering combinations
CREATE INDEX idx_query_logs_route_created ON query_logs(route, created_at DESC);
CREATE INDEX idx_query_logs_model_created ON query_logs(model_used, created_at DESC);
CREATE INDEX idx_query_logs_intent_created ON query_logs(intent, created_at DESC);
CREATE INDEX idx_query_logs_confidence_created ON query_logs(confidence_score DESC, created_at DESC);

-- Full text search on query_text and answer_text (optional, requires GIN index)
-- Uncomment if you want full-text search optimization
-- CREATE INDEX idx_query_logs_query_text_search ON query_logs USING GIN(to_tsvector('english', query_text || ' ' || COALESCE(answer_text, '')));

-- ============================================================================
-- SECTION 8: Verification Steps
-- ============================================================================

-- After running this migration, verify the new columns exist:
-- 
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'query_logs'
-- ORDER BY ordinal_position;
--
-- You should see all new columns in the output.

-- ============================================================================
-- SECTION 9: Rollback Script (if needed)
-- ============================================================================

/*
-- UNCOMMENT TO ROLLBACK - Use with caution!
-- This will remove all Phase 9 data.

DROP INDEX IF EXISTS idx_query_logs_user_role;
DROP INDEX IF EXISTS idx_query_logs_user_domain;
DROP INDEX IF EXISTS idx_query_logs_retrieval_strategy;
DROP INDEX IF EXISTS idx_query_logs_ticket_status;
DROP INDEX IF EXISTS idx_query_logs_verification_result;
DROP INDEX IF EXISTS idx_query_logs_user_created;
DROP INDEX IF EXISTS idx_query_logs_route_created;
DROP INDEX IF EXISTS idx_query_logs_model_created;
DROP INDEX IF EXISTS idx_query_logs_intent_created;
DROP INDEX IF EXISTS idx_query_logs_confidence_created;

ALTER TABLE query_logs DROP COLUMN IF EXISTS user_role;
ALTER TABLE query_logs DROP COLUMN IF EXISTS user_domain;
ALTER TABLE query_logs DROP COLUMN IF EXISTS retrieval_strategy;
ALTER TABLE query_logs DROP COLUMN IF EXISTS retrieved_chunk_ids;
ALTER TABLE query_logs DROP COLUMN IF EXISTS authorized_chunk_ids;
ALTER TABLE query_logs DROP COLUMN IF EXISTS retrieval_score;
ALTER TABLE query_logs DROP COLUMN IF EXISTS reranking_score;
ALTER TABLE query_logs DROP COLUMN IF EXISTS reranking_explanation;
ALTER TABLE query_logs DROP COLUMN IF EXISTS citation_count;
ALTER TABLE query_logs DROP COLUMN IF EXISTS verification_result;
ALTER TABLE query_logs DROP COLUMN IF EXISTS verification_details;
ALTER TABLE query_logs DROP COLUMN IF EXISTS ticket_id;
ALTER TABLE query_logs DROP COLUMN IF EXISTS ticket_status;
ALTER TABLE query_logs DROP COLUMN IF EXISTS chunk_access_violations;
ALTER TABLE query_logs DROP COLUMN IF EXISTS access_violation_details;
ALTER TABLE query_logs DROP COLUMN IF EXISTS retrieval_latency_ms;
ALTER TABLE query_logs DROP COLUMN IF EXISTS reranking_latency_ms;
ALTER TABLE query_logs DROP COLUMN IF EXISTS llm_latency_ms;
*/

-- ============================================================================
-- SECTION 10: Testing Script
-- ============================================================================

/*
-- Run this after migration to verify everything works

-- Test 1: Insert a complete query log row
INSERT INTO query_logs (
  query_id, user_id, user_role, user_domain,
  query_text, answer_text, intent, complexity, route, retrieval_strategy, model_used,
  retrieved_chunks, citation_count, confidence_score, is_grounded, was_rewritten,
  hallucinations_detected, verification_result, ticket_status,
  retrieval_score, reranking_score, latency_ms,
  retrieval_latency_ms, reranking_latency_ms, llm_latency_ms
)
VALUES (
  'QRY_test000001', '550e8400-e29b-41d4-a716-446655440000'::uuid, 'analyst', 'Engineering',
  'What is the system status?', 'The system is operational...', 'informational', 'simple', 'vector', 'vector', 'gpt-4',
  5, 2, 0.95, true, false, 0, 'verified', 'open',
  0.89, 0.92, 1500, 500, 300, 600
);

-- Test 2: Verify the data was inserted
SELECT query_id, user_role, user_domain, verification_result, 
       retrieval_score, reranking_score, latency_ms
FROM query_logs 
WHERE query_id = 'QRY_test000001';

-- Test 3: Test filtering by user_role
SELECT COUNT(*) as analyst_queries 
FROM query_logs 
WHERE user_role = 'analyst';

-- Test 4: Test filtering by confidence range
SELECT COUNT(*) as high_confidence_queries 
FROM query_logs 
WHERE confidence_score >= 0.8;

-- Test 5: Clean up test data
DELETE FROM query_logs WHERE query_id = 'QRY_test000001';
*/

-- ============================================================================
-- Migration Complete!
-- ============================================================================

-- The Phase 9 database migration is now complete.
-- 
-- You can now:
-- 1. Deploy the Phase 9 backend code
-- 2. Deploy the Phase 9 frontend code
-- 3. Start logging queries with all new fields
-- 4. Access /query-history to view query logs
--
-- Happy logging!
