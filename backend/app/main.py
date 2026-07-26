"""
FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"🚀 Starting {settings.app_name} [{settings.app_env}]")
    print(f"   LLM Provider : {settings.llm_provider}")
    print(f"   Embedding    : {settings.embedding_model}")
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    from app.services.graph_service import get_graph_service
    get_graph_service().close()
    print("👋 Shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    description="AI-powered backend with LangChain, FAISS, Neo4j & PostgreSQL",
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
app.include_router(router, prefix="/api/v1")


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Root"])
def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
