"""
SQLAlchemy declarative base and database initialization helpers.
All ORM models import Base from this module.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.database import Base, engine  # noqa: F401 – re-export for models

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create all tables that don't yet exist in the database."""
    # Import all models so SQLAlchemy registers them against Base.metadata
    from app.models import document          # noqa: F401
    from app.models import chunk             # noqa: F401  ← Phase 3: chunks table
    from app.models import document_change   # noqa: F401  ← Phase 6: evolution events
    from app.models import query_log         # noqa: F401  ← Phase 12: query telemetry
    from app.models import feedback          # noqa: F401  ← Phase 12: user feedback
    from app.models import user              # noqa: F401  ← Auth module: user accounts
    from app.models import ticket            # noqa: F401  ← Ticketing: low-confidence escalations
    from app.models import domain            # noqa: F401  ← User/Domain/Access Mgmt: domains table
    from app.models import user_domain       # noqa: F401  ← User/Domain/Access Mgmt: membership
    from app.models import audit_log         # noqa: F401  ← User/Domain/Access Mgmt: audit trail
    from app.models import document_access   # noqa: F401  ← Domain-Aware Document Metadata: RESTRICTED grants
    from app.models import ingestion_job     # noqa: F401  ← Data Injection Management: async job tracking
    from app.models import reindex_job       # noqa: F401  ← Chunk Indexing Management: async job tracking
    from app.models import llm_provider      # noqa: F401  ← LLM and Model Switching: provider configs
    from app.models import domain_routing_config  # noqa: F401  ← Phase 11: Domain routing configs
    from app.models import system_setting    # noqa: F401  ← Phase 10: Dynamic system settings
    from app.models import knowledge_update_request  # noqa: F401  ← Phase 14: Knowledge Evolution Requests
    from app.models import learning_signal   # noqa: F401  ← Phase 15: Continuous Learning signals
    from app.models import threshold_history # noqa: F401  ← Phase 15: Threshold audit trail
    Base.metadata.create_all(bind=engine)
    _run_light_migrations()
    _seed_default_domains()
    _seed_default_llm_provider()


def _run_light_migrations() -> None:
    """
    Apply additive column migrations that `create_all` cannot handle
    (it only creates missing *tables*, never alters existing ones).

    Phase 6 adds versioning columns to the pre-existing `documents` table.
    All statements are idempotent (ADD COLUMN IF NOT EXISTS).
    """
    statements = [
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS previous_version_id VARCHAR(64)",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_latest BOOLEAN NOT NULL DEFAULT TRUE",
        "CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)",
        # Google OAuth: password becomes optional, provenance + avatar columns.
        "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(20) NOT NULL DEFAULT 'local'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture VARCHAR(512)",
        # RBAC: role column (app.core.permissions.Role values).
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'guest_user'",
        # RBAC: resource-level ticket ownership for scoped GET /tickets.
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS raised_by_user_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_tickets_raised_by_user_id ON tickets (raised_by_user_id)",
        # RBAC: resource-level query-log ownership for scoped GET /query-logs.
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS user_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_query_logs_user_id ON query_logs (user_id)",
        # User/Domain/Access Management: department, timestamps.
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(256)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()",
        # Domain-Aware Document Metadata: access-control fields on documents.
        # `domains`/`users` already exist by this point (created above), so
        # the inline REFERENCES are safe to add here.
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES domains(id) ON DELETE SET NULL",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'domain'",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by_id UUID REFERENCES users(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_documents_domain_id ON documents (domain_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_owner_id ON documents (owner_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_uploaded_by_id ON documents (uploaded_by_id)",
        # ...and propagated (by reference) onto chunks for direct traceability.
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS document_version INTEGER",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS domain_id UUID",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS visibility VARCHAR(16)",
        "CREATE INDEX IF NOT EXISTS ix_chunks_domain_id ON chunks (domain_id)",
        # Chunk Indexing Management: per-chunk indexing state (see
        # app/models/chunk.py's CHUNK_INDEX_STATUSES). Existing rows all
        # already have a live FAISS vector by construction, so 'indexed' is
        # the correct default — no need to distinguish them from new rows.
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS index_status VARCHAR(16) NOT NULL DEFAULT 'indexed'",
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP WITH TIME ZONE",
        "CREATE INDEX IF NOT EXISTS ix_chunks_index_status ON chunks (index_status)",
        "UPDATE chunks SET indexed_at = created_at WHERE indexed_at IS NULL AND faiss_id IS NOT NULL",
        # One-time backfill: chunks whose document was already superseded
        # (is_latest=FALSE) before this phase existed are retroactively
        # 'stale' — guarded by index_status='indexed' so it never overwrites
        # a 'pending'/'failed' row a reindex job is actively working on.
        "UPDATE chunks SET index_status = 'stale' FROM documents "
        "WHERE chunks.document_id = documents.document_id AND documents.is_latest = FALSE "
        "AND chunks.index_status = 'indexed'",
        # Phase 10 & 11: Enterprise Ticketing columns on tickets table
        "ALTER TABLE tickets ALTER COLUMN query_text DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN answer_text DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN hallucinations_detected DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN hallucinations_detected SET DEFAULT 0",
        "ALTER TABLE tickets ALTER COLUMN department DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN source_document_ids DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN reviewer_notes DROP NOT NULL",
        "ALTER TABLE tickets ALTER COLUMN corrected_answer DROP NOT NULL",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS title VARCHAR(512)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS user_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_tickets_user_id ON tickets (user_id)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS original_question TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS generated_answer TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS confidence_threshold DOUBLE PRECISION",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS evidence TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'medium'",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS domain VARCHAR(256)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolution TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS feedback TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolver_user_id UUID",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1",
        "UPDATE tickets SET user_id = raised_by_user_id WHERE user_id IS NULL AND raised_by_user_id IS NOT NULL",
        "UPDATE tickets SET original_question = query_text WHERE original_question IS NULL AND query_text IS NOT NULL",
        "UPDATE tickets SET generated_answer = answer_text WHERE generated_answer IS NULL AND answer_text IS NOT NULL",
        "UPDATE tickets SET domain = department WHERE domain IS NULL AND department IS NOT NULL",
        "UPDATE tickets SET feedback = reviewer_notes WHERE feedback IS NULL AND reviewer_notes IS NOT NULL",
        "UPDATE tickets SET resolution = corrected_answer WHERE resolution IS NULL AND corrected_answer IS NOT NULL",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS routed_domain_id UUID REFERENCES domains(id) ON DELETE SET NULL",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS routing_confidence DOUBLE PRECISION",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS routing_method VARCHAR(32)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS routing_timestamp TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS needs_triage BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_tickets_routed_domain_id ON tickets (routed_domain_id)",
        "CREATE INDEX IF NOT EXISTS ix_tickets_needs_triage ON tickets (needs_triage)",
        # Phase 13: Domain Expert Ticket Resolution columns
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS resolution_type VARCHAR(64)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS supporting_evidence TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS supporting_document_ids TEXT",
        "CREATE INDEX IF NOT EXISTS ix_tickets_resolution_type ON tickets (resolution_type)",
        # Query Logs Phase 9 columns
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS user_role VARCHAR(32)",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS user_domain VARCHAR(256)",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS retrieval_strategy VARCHAR(32)",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS retrieved_chunk_ids VARCHAR[] DEFAULT '{}'",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS authorized_chunk_ids VARCHAR[] DEFAULT '{}'",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS retrieval_score DOUBLE PRECISION",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS reranking_score DOUBLE PRECISION",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS reranking_explanation TEXT",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS citation_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS verification_result VARCHAR(32)",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS verification_details TEXT",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS ticket_id UUID",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS ticket_status VARCHAR(32)",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS chunk_access_violations INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS access_violation_details TEXT",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS retrieval_latency_ms DOUBLE PRECISION",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS reranking_latency_ms DOUBLE PRECISION",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS llm_latency_ms DOUBLE PRECISION",
        # ── Phase 15: Feedback table – Continuous Learning integration columns ─────────
        "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ticket_id VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_feedback_ticket_id ON feedback (ticket_id)",
        "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS domain_routing_correct BOOLEAN",
        "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS retrieval_failure_flagged BOOLEAN",
    ]
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logger.info("[DB] Phase 6 versioning migrations applied.")
    except Exception as exc:  # pragma: no cover – non-Postgres or permission issue
        logger.warning("[DB] Light migrations skipped/failed: %s", exc)


# Starter set named in the Role & Access Matrix spec — ordinary rows, not a
# fixed enum: admins can rename/deactivate/add beyond these via
# POST/PATCH /api/v1/domains (Permission.DOMAIN_MANAGE). Seeding only INSERTs
# missing keys, so it never resurrects a domain an admin deliberately deleted...
# except this project never hard-deletes domains (deactivate only, see
# app/api/domains.py), so that scenario can't actually arise — noted for
# clarity, not because it's a real risk here.
_DEFAULT_DOMAINS = [
    ("hr", "HR", "Human Resources"),
    ("finance", "Finance", "Finance and Accounting"),
    ("it", "IT", "Information Technology"),
    ("operations", "Operations", "Operations"),
    ("legal", "Legal", "Legal and Compliance"),
    ("sales", "Sales", "Sales"),
    ("engineering", "Engineering", "Engineering"),
]


def _seed_default_domains() -> None:
    from app.db.database import SessionLocal
    from app.models.domain import Domain

    db = SessionLocal()
    try:
        existing_keys = {k for (k,) in db.query(Domain.key).all()}
        created = 0
        for key, name, description in _DEFAULT_DOMAINS:
            if key in existing_keys:
                continue
            db.add(Domain(key=key, name=name, description=description))
            created += 1
        if created:
            db.commit()
            logger.info("[DB] Seeded %d default domain(s).", created)
    except Exception as exc:  # pragma: no cover
        db.rollback()
        logger.warning("[DB] Domain seeding skipped/failed: %s", exc)
    finally:
        db.close()


def _seed_default_llm_provider() -> None:
    """
    Admin Panel: LLM and Model Switching — seed exactly one LLMProviderConfig
    row, mirroring whatever `.env` already specifies (settings.llm_provider),
    so a fresh install behaves identically to pre-Phase-8 (env-driven)
    behavior out of the box AND gives the admin panel something real to
    show/edit immediately. Only runs if the table is completely empty —
    never re-seeds or resurrects a config an admin has since deleted... except
    this project has no delete endpoint for these (deactivate only), so that
    scenario can't arise — same non-risk noted on _seed_default_domains above.
    """
    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.models.llm_provider import LLMProviderConfig

    db = SessionLocal()
    try:
        if db.query(LLMProviderConfig).count() > 0:
            return
        provider = settings.llm_provider.lower()
        if provider == "openai":
            model, endpoint, api_key_env_var = settings.openai_model, None, "OPENAI_API_KEY"
        elif provider == "groq":
            model, endpoint, api_key_env_var = settings.groq_model, None, "GROQ_API_KEY"
        else:
            provider, model, endpoint, api_key_env_var = "ollama", settings.ollama_model, settings.ollama_base_url, None
        db.add(LLMProviderConfig(
            name=f"Default ({provider})", provider=provider, model=model,
            endpoint=endpoint, api_key_env_var=api_key_env_var,
            temperature=settings.llm_temperature, status="active", is_current=True,
        ))
        db.commit()
        logger.info("[DB] Seeded default LLM provider config: %s/%s", provider, model)
    except Exception as exc:  # pragma: no cover
        db.rollback()
        logger.warning("[DB] LLM provider seeding skipped/failed: %s", exc)
    finally:
        db.close()
