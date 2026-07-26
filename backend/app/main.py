"""
FastAPI Application Entry Point
"""
import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import router as base_router
from app.api.documents import router as documents_router

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

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    from app.services.graph_service import get_graph_service
    get_graph_service().close()
    logger.info("👋 Shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Enterprise Knowledge Intelligence Platform – "
        "Module 1: Document Ingestion"
    ),
    version="1.0.0",
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
app.include_router(base_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Root"])
def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/api/v1/health",
        "upload": "/api/v1/documents/upload",
    }
