-- ============================================================================
-- Phase 15 Migration: Ticketing ↔ Continuous Learning
-- ============================================================================
-- Adds two new tables and extends the feedback table with learning signals.
-- All statements are idempotent (IF NOT EXISTS / IF EXISTS guards).
-- Run manually or via the app startup _run_light_migrations() auto-runner.
--
-- Tables created:
--   learning_signals     – append-only log of every discrete learning event
--   threshold_history    – auditable log of threshold suggestions + admin actions
--
-- Tables modified:
--   feedback             – 3 new nullable columns for Phase 15 signal capture
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. learning_signals table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learning_signals (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id           VARCHAR(64)  NOT NULL UNIQUE,
    signal_type         VARCHAR(32)  NOT NULL,

    -- Source references (nullable — depends on signal type)
    query_id            VARCHAR(64)  REFERENCES query_logs(query_id) ON DELETE SET NULL,
    ticket_id           VARCHAR(64),                  -- soft ref to tickets.ticket_id
    feedback_id         VARCHAR(64),                  -- soft ref to feedback.feedback_id
    domain_id           UUID         REFERENCES domains(id) ON DELETE SET NULL,

    -- Outcome signals (for confidence calibration)
    confidence_score    DOUBLE PRECISION,
    was_correct         VARCHAR(8),                   -- 'yes' | 'no' | 'partial'

    -- Retrieval context
    retrieval_route     VARCHAR(32),
    intent              VARCHAR(32),

    -- Resolution context (for ticket_resolved signals)
    resolution_type     VARCHAR(64),

    -- Flexible JSON payload
    details             TEXT,

    -- Audit
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_learning_signals_signal_id
    ON learning_signals (signal_id);

CREATE INDEX IF NOT EXISTS ix_learning_signals_signal_type
    ON learning_signals (signal_type);

CREATE INDEX IF NOT EXISTS ix_learning_signals_query_id
    ON learning_signals (query_id);

CREATE INDEX IF NOT EXISTS ix_learning_signals_ticket_id
    ON learning_signals (ticket_id);

CREATE INDEX IF NOT EXISTS ix_learning_signals_domain_id
    ON learning_signals (domain_id);

CREATE INDEX IF NOT EXISTS ix_learning_signals_created_at
    ON learning_signals (created_at);

CREATE INDEX IF NOT EXISTS ix_learning_signals_retrieval_route
    ON learning_signals (retrieval_route);

CREATE INDEX IF NOT EXISTS ix_learning_signals_intent
    ON learning_signals (intent);


-- ----------------------------------------------------------------------------
-- 2. threshold_history table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS threshold_history (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    history_id          VARCHAR(64)  NOT NULL UNIQUE,

    -- Which threshold
    metric_name         VARCHAR(64)  NOT NULL,

    -- The change
    old_value           DOUBLE PRECISION,
    new_value           DOUBLE PRECISION NOT NULL,

    -- Why
    reason              TEXT         NOT NULL,
    supporting_data     TEXT,                         -- JSON calibration stats

    -- Source: 'auto_suggestion' | 'admin_applied'
    source              VARCHAR(32)  NOT NULL,

    -- Admin action (if applied)
    approved_by         UUID         REFERENCES users(id) ON DELETE SET NULL,
    applied_at          TIMESTAMP WITH TIME ZONE,

    -- Back-reference to the suggestion this admin action is based on
    suggestion_id       VARCHAR(64),

    -- Audit
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_threshold_history_history_id
    ON threshold_history (history_id);

CREATE INDEX IF NOT EXISTS ix_threshold_history_metric_name
    ON threshold_history (metric_name);

CREATE INDEX IF NOT EXISTS ix_threshold_history_source
    ON threshold_history (source);

CREATE INDEX IF NOT EXISTS ix_threshold_history_approved_by
    ON threshold_history (approved_by);

CREATE INDEX IF NOT EXISTS ix_threshold_history_suggestion_id
    ON threshold_history (suggestion_id);

CREATE INDEX IF NOT EXISTS ix_threshold_history_created_at
    ON threshold_history (created_at);


-- ----------------------------------------------------------------------------
-- 3. Extend feedback table with Phase 15 columns
-- ----------------------------------------------------------------------------
ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS ticket_id               VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_feedback_ticket_id
    ON feedback (ticket_id);

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS domain_routing_correct  BOOLEAN;

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS retrieval_failure_flagged BOOLEAN;


-- ----------------------------------------------------------------------------
-- Done
-- ----------------------------------------------------------------------------
-- Verify:
--   SELECT COUNT(*) FROM learning_signals;      -- 0 (new table)
--   SELECT COUNT(*) FROM threshold_history;     -- 0 (new table)
--   SELECT column_name FROM information_schema.columns
--     WHERE table_name = 'feedback'
--     AND column_name IN ('ticket_id','domain_routing_correct','retrieval_failure_flagged');
-- ----------------------------------------------------------------------------
