"""
FastAPI Application Entry Point
"""
import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.permissions import router as permissions_router
from app.api.query_logs import router as query_logs_router
from app.api.domains import router as domains_router
from app.api.audit_logs import router as audit_logs_router
from app.api.routes import router as base_router
from app.api.documents import router as documents_router
from app.api.ingestion_jobs import router as ingestion_jobs_router
from app.api.chunks import router as chunks_router
from app.api.chunk_indexing import router as chunk_indexing_router
from app.api.rag import router as rag_router
from app.api.evolution import router as evolution_router
from app.api.query_intelligence import router as query_intelligence_router
from app.api.adaptive_retrieval import router as adaptive_retrieval_router
from app.api.context_fusion import router as context_fusion_router
from app.api.enterprise_llm import router as enterprise_llm_router
from app.api.llm_providers import router as llm_providers_router
from app.api.evidence_verification import router as evidence_verification_router
from app.api.feedback import router as feedback_router
from app.api.tickets import router as tickets_router
from app.api.domain_routing import router as domain_routing_router
from app.api.knowledge_updates import router as knowledge_updates_router
from app.api.learning import router as learning_router

# ── Logging configuration ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("🚀 Starting %s [%s]", settings.app_name, settings.app_env)
    logger.info("   LLM Provider : %s", settings.llm_provider)
    logger.info("   Embedding    : %s", settings.embedding_model)

    # Create database tables (idempotent – skips existing tables)
    from app.db.base import init_db
    init_db()
    logger.info("✅ Database tables initialised.")

    # Ensure the temp upload directory exists
    from app.utils.file_utils import ensure_temp_dir
    ensure_temp_dir()
    logger.info("📁 Temp upload dir: %s", settings.temp_upload_dir)

    # Phase 6 – Module 3: start the Document Change Monitor (folder watcher)
    from app.services.change_monitor import get_folder_watcher
    watcher = get_folder_watcher()
    if settings.watch_enabled:
        watcher.start()
        logger.info("👀 Folder watcher active: %s", settings.watch_dir)
    else:
        logger.info("👀 Folder watcher disabled (WATCH_ENABLED=false)")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    await watcher.stop()
    from app.services.graph_service import get_graph_service
    get_graph_service().close()
    logger.info("👋 Shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Enterprise Knowledge Intelligence Platform – "
        "Phase 15: Ticketing ⇔ Continuous Learning (learning signals, "
        "8 performance metrics, confidence calibration, controlled threshold "
        "management) on top of Phase 14's Ticket-Driven Knowledge Evolution, "
        "Phase 12's Continuous Learning Module (Module 10), Phase 11's "
        "Evidence Verification, Phase 10's Enterprise LLM, Phase 9's Context "
        "Fusion, Phase 8's Adaptive Retrieval Engine, Phase 7's Query "
        "Intelligence Module, and Phase 6's Knowledge Evolution Engine"
    ),
    version="1.15.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")     # Authentication Module
app.include_router(users_router, prefix="/api/v1")    # RBAC Foundation – User & Access Management
app.include_router(permissions_router, prefix="/api/v1")  # Role & Access Matrix – permission introspection
app.include_router(query_logs_router, prefix="/api/v1")   # Role & Access Matrix – Query Management
app.include_router(domains_router, prefix="/api/v1")       # User/Domain/Access Mgmt – Domain Management
app.include_router(audit_logs_router, prefix="/api/v1")    # User/Domain/Access Mgmt – Audit Log
app.include_router(base_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(ingestion_jobs_router, prefix="/api/v1")  # Admin Panel – Data Injection Management
app.include_router(chunks_router, prefix="/api/v1")   # Phase 3 – Module 2
app.include_router(chunk_indexing_router, prefix="/api/v1")  # Admin Panel – Chunk Indexing Management
app.include_router(rag_router, prefix="/api/v1")      # Phase 5 – RAG Pipeline
app.include_router(evolution_router, prefix="/api/v1")  # Phase 6 – Module 3 Evolution
app.include_router(query_intelligence_router, prefix="/api/v1")  # Phase 7 – Module 5 Query Intelligence
app.include_router(adaptive_retrieval_router, prefix="/api/v1")  # Phase 8 – Module 6 Adaptive Retrieval
app.include_router(context_fusion_router, prefix="/api/v1")      # Phase 9 – Module 7 Context Fusion
app.include_router(enterprise_llm_router, prefix="/api/v1")      # Phase 10 – Module 8 Enterprise LLM
app.include_router(llm_providers_router, prefix="/api/v1")       # Admin Panel – LLM and Model Switching
app.include_router(evidence_verification_router, prefix="/api/v1")  # Phase 11 – Module 9 Evidence Verification
app.include_router(feedback_router, prefix="/api/v1")             # Phase 12 – Module 10 Continuous Learning
app.include_router(tickets_router, prefix="/api/v1")              # Automatic Ticketing (low-confidence review queue)
app.include_router(domain_routing_router, prefix="/api/v1")       # Phase 11 – Domain-Based Ticket Routing
app.include_router(knowledge_updates_router, prefix="/api/v1")     # Phase 14 – Ticket-Driven Knowledge Evolution
app.include_router(learning_router, prefix="/api/v1")              # Phase 15 – Ticketing ⇔ Continuous Learning


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Root"])
def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/api/v1/health",
        "auth_register": "/api/v1/auth/register",
        "auth_login": "/api/v1/auth/login",
        "auth_me": "/api/v1/auth/me",
        "upload": "/api/v1/documents/upload",
        "ingestion_jobs": "/api/v1/ingestion-jobs/",
        "ingestion_stats": "/api/v1/ingestion-jobs/stats",
        "chunk_indexing_stats": "/api/v1/chunk-indexing/stats",
        "rag_query": "/api/v1/rag/query",
        "rag_status": "/api/v1/rag/status",
        "evolution_changes": "/api/v1/evolution/changes",
        "evolution_watcher": "/api/v1/evolution/watcher",
        "query_analyze": "/api/v1/query/analyze",
        "retrieval_route": "/api/v1/retrieval/route",
        "context_fuse": "/api/v1/context/fuse",
        "llm_models": "/api/v1/llm/models",
        "llm_providers": "/api/v1/llm-providers/",
        "verification_verify": "/api/v1/verification/verify",
        "feedback_submit": "/api/v1/feedback/submit",
        "feedback_metrics": "/api/v1/feedback/metrics/summary",
    }
