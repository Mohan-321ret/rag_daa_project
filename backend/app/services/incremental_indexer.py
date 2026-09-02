"""
Incremental Indexer  –  Phase 6 Module 3 (Step 5)
---------------------------------------------------
Instead of rebuilding the whole index when a document changes, only the
CHANGED chunks are (re)embedded:

  new version chunks
        ↓  match against old chunks by content hash (SHA-256)
  unchanged chunks  →  REUSE old embedding + FAISS vector (metadata repointed)
  changed/new      →  NEW embeddings  →  appended to FAISS
  removed chunks   →  FAISS vectors tombstoned (excluded from search)

This turns re-indexing cost from O(all chunks) into O(changed chunks).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.services.chunking_service import TextChunk
from app.services.embedding_service import embed_batch
from app.services.processing_pipeline import StageCallback
from app.services.storage_service import StorageService
from app.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def _noop_stage(stage: str, status: str, error: Optional[str] = None) -> None:
    pass


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


@dataclass
class ReindexResult:
    """Statistics + embeddings produced by an incremental reindex run."""
    chunks_unchanged: int = 0
    chunks_added: int = 0        # brand-new / modified chunks
    chunks_removed: int = 0      # old chunks that disappeared
    embeddings_reused: int = 0
    embeddings_computed: int = 0
    faiss_ids: List[int] = field(default_factory=list)
    # {chunk_index: embedding} maps, consumed by the drift detector (Step 3)
    old_embeddings: Dict[int, List[float]] = field(default_factory=dict)
    new_embeddings: Dict[int, List[float]] = field(default_factory=dict)


def reindex_incrementally(
    db: Session,
    old_document_id: str,
    new_document_id: str,
    new_chunks: List[TextChunk],
    language: str,
    on_stage: Optional[StageCallback] = None,
) -> ReindexResult:
    """
    Incrementally index the new version of a document.

    Args:
        db:               Active SQLAlchemy session.
        old_document_id:  DOC id of the previous version (chunks already indexed).
        new_document_id:  DOC id of the incoming version.
        new_chunks:       Chunks produced from the new version's cleaned text.
        language:         Detected language (stored in FAISS metadata).
        on_stage:         Optional StageCallback — see processing_pipeline.py's
                          module docstring. Reused here so a new-VERSION
                          upload gets the same real embedding/vector_index/
                          postgres_metadata/neo4j progress a new-DOCUMENT
                          upload does.

    Returns:
        ReindexResult with reuse/compute statistics and both embedding maps.
    """
    on_stage = on_stage or _noop_stage
    storage = StorageService(db)
    store = get_vector_store()
    result = ReindexResult()

    old_chunk_rows: List[Chunk] = storage.get_chunks(old_document_id)

    # Index old chunks by content hash (a hash may occur more than once)
    old_by_hash: Dict[str, List[Chunk]] = {}
    for row in old_chunk_rows:
        old_by_hash.setdefault(_hash_text(row.text), []).append(row)
        if row.embedding:
            try:
                result.old_embeddings[row.chunk_index] = json.loads(row.embedding)
            except (ValueError, TypeError):
                pass

    # ── Match new chunks against old ones ────────────────────────────────────
    reused: List[tuple[TextChunk, Chunk]] = []   # (new_chunk, matching_old_row)
    to_embed: List[TextChunk] = []

    for chunk in new_chunks:
        bucket = old_by_hash.get(_hash_text(chunk.text))
        if bucket:
            reused.append((chunk, bucket.pop(0)))   # consume one old match
        else:
            to_embed.append(chunk)

    # Old chunks left unmatched have been removed/modified → tombstone them
    removed_faiss_ids = [
        row.faiss_id
        for bucket in old_by_hash.values()
        for row in bucket
        if row.faiss_id is not None
    ]

    # ── Embed ONLY the changed/new chunks ────────────────────────────────────
    on_stage("embedding", "running")
    new_vectors: List[List[float]] = []
    if to_embed:
        logger.info(
            "[IncrementalIndexer] Embedding %d changed chunk(s) "
            "(reusing %d, removing %d)",
            len(to_embed), len(reused), len(removed_faiss_ids),
        )
        try:
            new_vectors = embed_batch([c.text for c in to_embed])
        except Exception as exc:
            on_stage("embedding", "failed", str(exc))
            raise
    else:
        logger.info(
            "[IncrementalIndexer] No changed chunks – reusing all %d embeddings.",
            len(reused),
        )
    on_stage("embedding", "completed")
    on_stage("vector_index", "running")

    # Domain-Aware Chunk Access Control: see processing_pipeline.py's matching
    # comment — domain_id/visibility ride along in FAISS metadata as a fast-
    # path optimization for in-loop authorization filtering during retrieval.
    new_doc_row = storage.get_by_document_id(new_document_id)
    doc_domain_id = str(new_doc_row.domain_id) if new_doc_row and new_doc_row.domain_id else None
    doc_visibility = new_doc_row.visibility if new_doc_row else None

    def _metadata(chunk: TextChunk) -> dict:
        return {
            "document_id": new_document_id,
            "chunk_index": chunk.index,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "word_count": chunk.word_count,
            "language": language,
            "domain_id": doc_domain_id,
            "visibility": doc_visibility,
        }

    # ── Reused chunks: repoint existing FAISS vectors at the new version ─────
    chunks_with_embeddings: List[tuple] = []
    for chunk, old_row in reused:
        embedding = json.loads(old_row.embedding) if old_row.embedding else []
        if old_row.faiss_id is not None:
            store.update_metadata(old_row.faiss_id, _metadata(chunk))
        chunks_with_embeddings.append((chunk, embedding, old_row.faiss_id))
        result.new_embeddings[chunk.index] = embedding

    # ── Changed chunks: append their fresh vectors to FAISS ──────────────────
    if to_embed:
        added_ids = store.add_batch_precomputed(
            [c.text for c in to_embed],
            new_vectors,
            [_metadata(c) for c in to_embed],
        )
        for chunk, embedding, fid in zip(to_embed, new_vectors, added_ids):
            chunks_with_embeddings.append((chunk, embedding, fid))
            result.new_embeddings[chunk.index] = embedding

    # ── Tombstone vectors of removed chunks ──────────────────────────────────
    if removed_faiss_ids:
        store.mark_deleted(removed_faiss_ids)

    # Persist metadata retargeting even when nothing new was appended
    store.save()
    on_stage("vector_index", "completed")

    # ── Persist the new version's chunk rows to PostgreSQL ───────────────────
    on_stage("postgres_metadata", "running")
    chunks_with_embeddings.sort(key=lambda t: t[0].index)
    try:
        storage.save_chunks(new_document_id, chunks_with_embeddings)
    except Exception as exc:
        on_stage("postgres_metadata", "failed", str(exc))
        raise
    on_stage("postgres_metadata", "completed")

    # ── Refresh BM25 + Knowledge Graph indexes (Phase 8 – Module 6) ──────────
    # The old version's graph presence is dropped by evolution_service when it
    # supersedes old_document_id; here we only need to (re)index the new one.
    from app.services.bm25_retriever import get_bm25_store
    get_bm25_store().invalidate()

    on_stage("neo4j", "running")
    from app.services.graph_retriever import get_graph_retriever
    from app.services.ner_service import extract_entities
    graph_retriever = get_graph_retriever()
    for chunk in new_chunks:
        graph_retriever.index_chunk_entities(
            new_document_id, chunk.index, extract_entities(chunk.text),
            domain_id=doc_domain_id, visibility=doc_visibility,
        )
    on_stage("neo4j", "completed")

    result.chunks_unchanged = len(reused)
    result.chunks_added = len(to_embed)
    result.chunks_removed = len(removed_faiss_ids)
    result.embeddings_reused = len(reused)
    result.embeddings_computed = len(to_embed)
    result.faiss_ids = [fid for _, _, fid in chunks_with_embeddings if fid is not None]

    logger.info(
        "[IncrementalIndexer] ✅ %s → %s | unchanged=%d added=%d removed=%d "
        "| embeddings computed=%d reused=%d",
        old_document_id, new_document_id,
        result.chunks_unchanged, result.chunks_added, result.chunks_removed,
        result.embeddings_computed, result.embeddings_reused,
    )
    return result
