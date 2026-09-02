"""
Chunks API Router  –  Phase 3 Module 2
----------------------------------------
Endpoints for querying semantic chunks produced during document ingestion.

  GET  /api/v1/chunks/{document_id}              – list all chunks for a doc
  GET  /api/v1/chunks/{document_id}/{chunk_index} – get a specific chunk
  POST /api/v1/chunks/search                      – semantic search across all chunks
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.user import User
from app.schemas.chunk import ChunkListResponse, ChunkOut, ChunkSearchResponse
from app.services.auth_service import current_role, require_permission
from app.services.chunk_access_service import build_chunk_access_context, filter_authorized_results
from app.services.document_access_service import assert_document_visible
from app.services.storage_service import StorageService
from app.services.vector_store import get_vector_store
from app.models.schemas import SearchRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chunks", tags=["Chunks"])


# ── GET /chunks/{document_id} ─────────────────────────────────────────────────

@router.get(
    "/{document_id}",
    response_model=ChunkListResponse,
    summary="List all chunks for a document",
    description=(
        "Returns all semantic chunks produced during Phase 3 processing "
        "for the given document, ordered by chunk_index."
    ),
)
def list_chunks(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
):
    """Retrieve all chunks for a document."""
    storage = StorageService(db)

    # Verify document exists
    doc = storage.get_by_document_id(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    # Domain-Aware Chunk Access Control: this endpoint is a direct
    # document-scoped bypass of the RAG retrieval pipeline if left
    # ungated — reuse the same document-registry visibility check
    # POST /documents/{id} already applies (Phase 4).
    assert_document_visible(db, current_user, caller_role, doc)

    chunks = storage.get_chunks(document_id)
    logger.info(
        "[ChunksAPI] Listing %d chunks for document %s", len(chunks), document_id
    )

    return ChunkListResponse(
        document_id=document_id,
        total=len(chunks),
        chunks=[ChunkOut.model_validate(c) for c in chunks],
    )


# ── GET /chunks/{document_id}/{chunk_index} ───────────────────────────────────

@router.get(
    "/{document_id}/{chunk_index}",
    response_model=ChunkOut,
    summary="Get a specific chunk by index",
)
def get_chunk(
    document_id: str,
    chunk_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
):
    """Return a single chunk by its index within the document."""
    from app.models.chunk import Chunk

    storage = StorageService(db)
    doc = storage.get_by_document_id(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    assert_document_visible(db, current_user, caller_role, doc)

    chunk = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == document_id,
            Chunk.chunk_index == chunk_index,
        )
        .first()
    )

    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Chunk index {chunk_index} not found "
                f"for document '{document_id}'."
            ),
        )

    return ChunkOut.model_validate(chunk)


# ── POST /chunks/search ───────────────────────────────────────────────────────

@router.post(
    "/search",
    response_model=ChunkSearchResponse,
    summary="Semantic search across all indexed chunks",
    description=(
        "Uses FAISS vector similarity to find the most relevant chunks "
        "for the given query. Returns top-k results with similarity scores."
    ),
)
def search_chunks(
    body: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.CHUNK_VIEW)),
    caller_role: Role = Depends(current_role),
):
    """
    Perform semantic similarity search over indexed chunks.

    Domain-Aware Chunk Access Control: this is a raw retrieval endpoint —
    exactly the kind of direct bypass that would defeat /rag/query's
    authorization filtering if left unguarded. Fast in-loop filtering
    during the FAISS scan, THEN the same authoritative Postgres re-check
    every other retrieval path uses (see chunk_access_service.py).
    """
    store = get_vector_store()

    if store.total == 0:
        return ChunkSearchResponse(
            query=body.query,
            total_indexed=0,
            results=[],
        )

    access_ctx = build_chunk_access_context(db, current_user, caller_role)
    raw = store.search(body.query, top_k=body.top_k, filter_fn=access_ctx.as_filter_fn())
    tagged = [{**r, "document_id": r.get("metadata", {}).get("document_id")} for r in raw]
    results = filter_authorized_results(db, tagged, access_ctx)

    logger.info(
        "[ChunksAPI] Semantic search | query='%s...' hits=%d",
        body.query[:50], len(results),
    )

    return ChunkSearchResponse(
        query=body.query,
        total_indexed=store.total,
        results=results,
    )
