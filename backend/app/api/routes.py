"""API route definitions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.core.config import settings
from app.db.database import check_db_connection
from app.services.graph_service import get_graph_service
from app.services.llm_service import generate_response
from app.services.embedding_service import embed_text
from app.services.vector_store import get_vector_store
from app.models.schemas import (
    HealthResponse,
    PromptRequest, LLMResponse,
    EmbedRequest, EmbedResponse,
    AddDocumentRequest, AddDocumentResponse,
    SearchRequest, SearchResponse, SearchResult,
    NodeRequest, RelationshipRequest,
)

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    """Full service health check."""
    graph_ok = get_graph_service().is_connected()
    db_ok = check_db_connection()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.app_env,
        services={
            "postgres": "ok" if db_ok else "unreachable",
            "neo4j": "ok" if graph_ok else "unreachable",
            "llm_provider": settings.llm_provider,
        },
    )


# ── LLM ───────────────────────────────────────────────────────────────────────

@router.post("/llm/generate", response_model=LLMResponse, tags=["LLM"])
async def llm_generate(body: PromptRequest):
    """Send a prompt to the configured LLM and return its response."""
    try:
        text = await generate_response(body.prompt)
        return LLMResponse(response=text, provider=settings.llm_provider)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── Embeddings ────────────────────────────────────────────────────────────────

@router.post("/embeddings/embed", response_model=EmbedResponse, tags=["Embeddings"])
def get_embedding(body: EmbedRequest):
    """Return the embedding vector for the given text."""
    vector = embed_text(body.text)
    return EmbedResponse(
        embedding=vector,
        model=settings.embedding_model,
        dimension=len(vector),
    )


# ── Vector Store ──────────────────────────────────────────────────────────────

@router.post("/vectors/add", response_model=AddDocumentResponse, tags=["Vector Store"])
def add_document(body: AddDocumentRequest):
    store = get_vector_store()
    doc_id = store.add(body.text, body.metadata)
    return AddDocumentResponse(id=doc_id, message="Document indexed successfully.")


@router.post("/vectors/search", response_model=SearchResponse, tags=["Vector Store"])
def search_documents(body: SearchRequest):
    store = get_vector_store()
    raw = store.search(body.query, top_k=body.top_k)
    return SearchResponse(
        results=[SearchResult(**r) for r in raw],
        total_indexed=store.total,
    )


# ── Graph (Neo4j) ─────────────────────────────────────────────────────────────

@router.post("/graph/node", tags=["Graph"])
def create_graph_node(body: NodeRequest):
    """Create a Neo4j node and return its properties."""
    svc = get_graph_service()
    node = svc.create_node(body.label, body.properties)
    return {"node": node}


@router.get("/graph/nodes/{label}", tags=["Graph"])
def get_graph_nodes(label: str):
    """Return all nodes of the given label (max 100)."""
    svc = get_graph_service()
    nodes = svc.find_nodes(label)
    return {"nodes": nodes, "count": len(nodes)}


@router.post("/graph/relationship", tags=["Graph"])
def create_graph_relationship(body: RelationshipRequest):
    svc = get_graph_service()
    success = svc.create_relationship(
        body.from_label, body.from_props,
        body.rel_type,
        body.to_label, body.to_props,
        body.rel_props,
    )
    return {"success": success}
