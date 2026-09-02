from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "FinalYear Project API"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change_me"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/finalyear_db"
    )

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "groq"  # groq | ollama | openai

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.6-27b"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # Options: all-MiniLM-L6-v2 (dim=384) | BAAI/bge-large-en-v1.5 (dim=1024)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ── FAISS ─────────────────────────────────────────────────────────────────
    faiss_index_path: str = "./data/faiss_index"

    # ── Document Ingestion ────────────────────────────────────────────────────
    max_upload_size_mb: int = 25
    temp_upload_dir: str = "./data/tmp_uploads"
    doc_id_prefix: str = "DOC"
    # Comma-separated list of allowed extensions
    allowed_extensions: str = ".pdf,.docx,.txt,.html,.pptx"

    # ── Chunking (Module 2 – Phase 3) ─────────────────────────────────────────
    chunk_size: int = 1000          # target characters per chunk
    chunk_overlap: int = 200        # overlap characters between consecutive chunks
    chunk_min_length: int = 50      # discard chunks shorter than this

    # ── Knowledge Evolution Engine (Module 3 – Phase 6) ───────────────────────
    # Step 1 – Document Change Monitor (folder watcher)
    watch_enabled: bool = True
    watch_dir: str = "./data/watched_docs"
    watch_poll_interval_s: int = 10

    # Step 3 – Concept Drift Detection (cosine similarity thresholds)
    drift_threshold: float = 0.80        # doc-level: below this ⇒ concept changed
    chunk_drift_threshold: float = 0.75  # chunk-level: below this ⇒ chunk drifted

    # Step 4 – Conflict Detection
    conflict_fuzzy_threshold: float = 0.75  # min statement similarity to pair sentences
    max_conflicts_reported: int = 20

    # Step 2 – Version Comparator
    max_diff_chars: int = 20000          # cap stored unified diff size

    # ── Query Intelligence Module (Module 5 – Phase 7) ────────────────────────
    # Step 3 – NER
    spacy_model: str = "en_core_web_sm"

    # Step 2 – Intent Detection: "heuristic" (fast, rule-based) | "llm" (few-shot)
    intent_detection_method: str = "heuristic"
    intent_llm_confidence: float = 0.75  # confidence assigned to LLM-classified intents

    # Step 4 – Complexity Analyzer thresholds (score 0..~10, see complexity_analyzer.py)
    complexity_medium_threshold: float = 3.0
    complexity_complex_threshold: float = 6.0

    # RAG integration: scale top_k retrieval by query complexity
    complexity_top_k_medium: int = 8
    complexity_top_k_complex: int = 12

    # ── Adaptive Retrieval Engine (Module 6 – Phase 8) ────────────────────────
    # Router: keyword/regex trigger for the "exact policy number" → BM25 route
    policy_number_pattern: str = (
        r"\b(?:policy|clause|section|article|regulation|rule|paragraph)\s*"
        r"(?:no\.?|number|#)?\s*\d+(?:\.\d+)*\b"
        r"|\b[A-Z]{2,6}[-_]\d{2,6}\b"
        r"|\b\d+\.\d+(?:\.\d+)+\b"
    )
    # Router: keyword trigger for the "relationship" → Knowledge Graph route
    relationship_keywords: str = (
        "relationship between,related to,relation to,connected to,connection between,"
        "reports to,reporting to,part of,belongs to,managed by,linked to,"
        "associated with,works with,works under,depends on,affects,impacts,"
        "responsible for,owned by,parent of,subsidiary of,who owns,who manages"
    )

    bm25_top_k: int = 5
    graph_top_k: int = 5
    hybrid_rrf_k: int = 60          # Reciprocal Rank Fusion smoothing constant

    @property
    def relationship_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.relationship_keywords.split(",") if k.strip()]

    # ── Context Fusion (Module 7 – Phase 9) ────────────────────────────────────
    # Step: Duplicate Removal – near-duplicate chunks (e.g. overlapping windows
    # from chunk_overlap, or the same passage surfaced by 2+ retrieval routes)
    dedup_similarity_threshold: float = 0.85   # Jaccard shingle similarity, 0..1
    dedup_shingle_size: int = 5                 # word n-gram size for near-dup detection

    # Step: Cross Encoder Ranking – precise (query, chunk) relevance re-scoring
    cross_encoder_enabled: bool = True
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Step: Context Compression – fit the reranked chunks into a token/char budget
    context_max_chars: int = 6000               # total optimized-context budget
    context_chunk_max_chars: int = 800           # per-chunk cap after sentence trimming
    context_min_sentences_per_chunk: int = 1     # always keep at least this many sentences

    # ── Enterprise LLM (Module 8 – Phase 10) ──────────────────────────────────
    # Alias registry so callers can request "llama3" / "gemma" / "mistral" /
    # "qwen" without knowing the exact Ollama tag. Format: alias=tag,alias=tag
    # (an unknown alias is treated as a literal Ollama tag, so exact tags like
    # "llama3:70b" or "gemma3:4b" still work even when not listed here).
    llm_model_registry: str = "llama3=llama3,gemma=gemma2,mistral=mistral,qwen=qwen2.5"
    llm_default_model_alias: str = "llama3"
    llm_temperature: float = 0.7

    @property
    def llm_model_registry_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for pair in self.llm_model_registry.split(","):
            if "=" in pair:
                alias, tag = pair.split("=", 1)
                mapping[alias.strip().lower()] = tag.strip()
        return mapping

    # ── Evidence Verification (Module 9 – Phase 11) ───────────────────────────
    verification_enabled: bool = True
    verification_evidence_top_k: int = 3        # evidence chunks retrieved per claim
    # Semantic (embedding cosine) similarity above which an evidence sentence is
    # considered to be "about the same fact" as a claim. Lexical/masked-text
    # similarity was tried first and failed on realistic LLM paraphrasing (e.g.
    # "Leave policy is 30 days" vs "Employees receive 25 annual leave days per
    # calendar year" scores ~0.39 lexically but ~0.69 semantically) — embeddings
    # are what actually bridge that gap.
    verification_statement_similarity_threshold: float = 0.45
    verification_min_claim_chars: int = 8        # discard trivially short sentences

    # ── Continuous Learning (Module 10 – Phase 12) ────────────────────────────
    query_logging_enabled: bool = True     # Store step: log every /rag/query call
    continuous_learning_enabled: bool = True   # gate Improve Routing / Improve Retrieval

    # A route/intent needs at least this many rated queries before its
    # satisfaction score is trusted enough to influence future decisions
    # (avoids overreacting to 1-2 noisy thumbs-down).
    learning_min_samples: int = 5
    # Below this satisfaction ratio (0..1), a route is considered underperforming.
    learning_satisfaction_threshold: float = 0.5
    # How much to widen top_k for an underperforming route (capped multiplier).
    learning_topk_boost: float = 1.5
    learning_topk_boost_max: int = 20

    # Default aggregation window for GET /feedback/metrics when not specified.
    metrics_default_window_days: int = 30

    # ── Automatic Ticketing (Module 1 – Phase 10) ──────────────────────────────
    # When a /rag/query answer's verification confidence_score falls below the
    # threshold, a review ticket is raised automatically. The threshold is
    # configurable and can be updated by admins via API.
    ticketing_enabled: bool = True
    ticket_confidence_threshold: float = 0.5  # Min confidence to avoid ticket (0-1)
    ticket_default_priority: str = "medium"   # Priority if not calculated
    ticket_default_domain: str = "General"    # Fallback domain for tickets
    ticket_priority_cutoff_critical: float = 0.3  # confidence < this = CRITICAL
    ticket_priority_cutoff_high: float = 0.5     # confidence < this = HIGH
    ticket_priority_cutoff_medium: float = 0.75  # confidence < this = MEDIUM
    ticket_priority_cutoff_low: float = 0.9      # confidence < this = LOW
    # Auto-increment ticket ID prefix
    ticket_id_prefix: str = "TKT"

    # ── Domain-Based Ticket Routing (Phase 11) ────────────────────────────
    domain_routing_enabled: bool = True          # Master switch for auto domain routing
    domain_routing_confidence_threshold: float = 0.5  # Below this → NEEDS_TRIAGE
    domain_routing_llm_enabled: bool = True      # Enable/disable LLM fallback classifier
    domain_routing_triage_admin_role: str = "super_admin"  # Who gets NEEDS_TRIAGE tickets

    # ── Authentication (JWT) ───────────────────────────────────────────────────
    # Signing key reuses `secret_key` above (already existed, unused until now).
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # ── Authentication (Google OAuth) ─────────────────────────────────────────
    # OAuth 2.0 Web client ID from Google Cloud Console → Credentials.
    # The frontend renders the Google Sign-In button with the same client ID
    # (NEXT_PUBLIC_GOOGLE_CLIENT_ID) and POSTs the resulting ID token to
    # /auth/google, which verifies it against this audience. Empty ⇒ the
    # endpoint returns 503 and the frontend hides the button.
    google_client_id: str = ""

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Includes Vite's default dev port (5173) alongside the Docker Compose
    # frontend port (3000) so the Authentication module's login flow works
    # against either `npm run dev` or the containerized frontend out of the box.
    allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_extensions.split(",")]

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


settings = Settings()

