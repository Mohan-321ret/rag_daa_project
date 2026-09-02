"""
Chunk Indexing Service  –  Admin Panel: Chunk Indexing Management
----------------------------------------------------------------------
The actual re-indexing work: re-embed chunk text, write/tombstone FAISS
vectors, refresh Neo4j entities, and keep PostgreSQL's `Chunk.index_status`
in sync — for every operation the admin panel exposes:

  reindex chunks / a document / a domain   -> _run_generic_reindex
  retry failed chunks                      -> _run_generic_reindex
  remove stale vectors                     -> run_remove_stale_job
  full index rebuild                       -> run_full_rebuild_job

Every entry point here is a FastAPI BackgroundTask body (see
app/api/chunk_indexing.py) — each opens its OWN SessionLocal(), same
reasoning as app/services/ingestion_job_service.py's background functions.

Consistency across the three stores, per chunk touched:
  1. Embedding  – re-run embed_batch() on the chunk's stored text (no
                  re-extraction/re-chunking; boundaries never move here).
  2. FAISS      – tombstone the old vector (if any), append a fresh one.
  3. PostgreSQL – update faiss_id/embedding/index_status/indexed_at.
  4. Neo4j      – re-run NER + index_chunk_entities (MERGE-based, so
                  re-indexing the same chunk is idempotent, not a duplicate).
  5. BM25       – invalidated once per job (its corpus is rebuilt lazily
                  from PostgreSQL on the next search, same as every other
                  chunk-population change in this codebase).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from app.db.database import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document
from app.services import reindex_job_service
from app.services.embedding_service import embed_batch
from app.services.graph_retriever import get_graph_retriever
from app.services.ner_service import extract_entities
from app.services.reindex_job_service import ProgressReporter
from app.services.vector_store import FAISSVectorStore, get_vector_store

logger = logging.getLogger(__name__)

BATCH_SIZE = 32


def _reindex_chunk_batch(db, store: FAISSVectorStore, chunks: List[Chunk]) -> List[Tuple[Chunk, bool, Optional[str]]]:
    """
    Re-embed and re-index one batch of chunks in a single FAISS write.
    Always leaves every chunk's index_status in a terminal state
    ('indexed' or 'failed') before returning — callers just report results.
    """
    now = datetime.now(timezone.utc)
    texts = [c.text for c in chunks]

    try:
        vectors = embed_batch(texts)
        metadatas = [
            {
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "word_count": c.word_count,
                "domain_id": str(c.domain_id) if c.domain_id else None,
                "visibility": c.visibility,
            }
            for c in chunks
        ]
        new_ids = store.add_batch_precomputed(texts, vectors, metadatas)
    except Exception as exc:
        logger.error("[ChunkIndexing] Batch of %d chunk(s) failed to embed/index: %s", len(chunks), exc)
        for c in chunks:
            c.index_status = "failed"
        db.commit()
        return [(c, False, str(exc)) for c in chunks]

    old_ids = [c.faiss_id for c in chunks if c.faiss_id is not None]
    if old_ids:
        store.mark_deleted(old_ids)

    results: List[Tuple[Chunk, bool, Optional[str]]] = []
    for c, vec, nid in zip(chunks, vectors, new_ids):
        c.faiss_id = nid
        c.embedding = json.dumps(vec)
        c.index_status = "indexed"
        c.indexed_at = now
        results.append((c, True, None))
    db.commit()

    graph = get_graph_retriever()
    for c in chunks:
        graph.index_chunk_entities(
            c.document_id, c.chunk_index, extract_entities(c.text),
            domain_id=str(c.domain_id) if c.domain_id else None, visibility=c.visibility,
        )

    return results


def _run_generic_reindex(job_id: str, select_chunks: Callable[..., List[Chunk]]) -> None:
    """
    Shared job body for every "re-embed these chunks" operation (selected
    chunks / a document / a domain / retry-failed) — only the SELECTION of
    which chunks to process differs between them.
    """
    db = SessionLocal()
    reporter = ProgressReporter(db, job_id)
    try:
        reporter.start()
        chunks = select_chunks(db)
        for c in chunks:
            c.index_status = "pending"
        db.commit()

        store = get_vector_store()
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            for c, success, error in _reindex_chunk_batch(db, store, batch):
                reporter.advance(success=success, ref=f"{c.document_id}:{c.chunk_index}", error=error)

        if chunks:
            from app.services.bm25_retriever import get_bm25_store
            get_bm25_store().invalidate()

        reindex_job_service.mark_completed(db, job_id)
    except Exception as exc:
        logger.error("[ChunkIndexing] Job %s failed: %s", job_id, exc)
        reindex_job_service.mark_failed(db, job_id, str(exc))
    finally:
        db.close()


# Every selection query below excludes index_status='stale': a stale chunk
# belongs to a document version that's no longer the latest, and
# re-embedding it would silently resurrect superseded content back into
# the live index — exactly what remove-stale exists to prevent. Stale
# chunks can only be acted on via run_remove_stale_job (or implicitly
# retired by run_full_rebuild_job, which never re-adds them at all).

def run_reindex_chunks_job(job_id: str, chunk_ids: List[str]) -> None:
    _run_generic_reindex(job_id, lambda db: db.query(Chunk).filter(Chunk.id.in_(chunk_ids), Chunk.index_status != "stale").all())


def run_reindex_document_job(job_id: str, document_id: str) -> None:
    _run_generic_reindex(job_id, lambda db: db.query(Chunk).filter(Chunk.document_id == document_id, Chunk.index_status != "stale").all())


def run_reindex_domain_job(job_id: str, domain_id: str) -> None:
    _run_generic_reindex(job_id, lambda db: db.query(Chunk).filter(Chunk.domain_id == domain_id, Chunk.index_status != "stale").all())


def run_retry_failed_job(job_id: str, document_id: Optional[str] = None, domain_id: Optional[str] = None) -> None:
    def select(db):
        q = db.query(Chunk).filter(Chunk.index_status == "failed")
        if document_id:
            q = q.filter(Chunk.document_id == document_id)
        if domain_id:
            q = q.filter(Chunk.domain_id == domain_id)
        return q.all()

    _run_generic_reindex(job_id, select)


def run_remove_stale_job(job_id: str, document_id: Optional[str] = None, domain_id: Optional[str] = None) -> None:
    """
    Tombstones the FAISS vector for every stale chunk in scope (never
    re-embeds — a stale chunk belongs to a superseded document version, so
    there's nothing worth indexing again, only cleaning up). The Chunk row
    itself is kept (index_status stays 'stale') as a historical record,
    consistent with this codebase's "never hard-delete" convention for
    documents/domains — only its faiss_id is cleared to reflect that no
    vector exists for it anymore.
    """
    db = SessionLocal()
    reporter = ProgressReporter(db, job_id)
    try:
        reporter.start()
        q = db.query(Chunk).filter(Chunk.index_status == "stale", Chunk.faiss_id.isnot(None))
        if document_id:
            q = q.filter(Chunk.document_id == document_id)
        if domain_id:
            q = q.filter(Chunk.domain_id == domain_id)
        chunks = q.all()

        store = get_vector_store()
        for c in chunks:
            try:
                store.mark_deleted([c.faiss_id])
                c.faiss_id = None
                db.commit()
                reporter.advance(success=True, ref=f"{c.document_id}:{c.chunk_index}")
            except Exception as exc:
                db.rollback()
                reporter.advance(success=False, ref=f"{c.document_id}:{c.chunk_index}", error=str(exc))

        reindex_job_service.mark_completed(db, job_id)
    except Exception as exc:
        logger.error("[ChunkIndexing] remove-stale job %s failed: %s", job_id, exc)
        reindex_job_service.mark_failed(db, job_id, str(exc))
    finally:
        db.close()


def run_full_rebuild_job(job_id: str) -> None:
    """
    Wipes the ENTIRE FAISS index and rebuilds it from scratch using only
    chunks belonging to a document's latest version (Document.is_latest) —
    stale/superseded chunks are intentionally excluded, so a full rebuild
    also permanently reclaims the space tombstoned vectors were holding
    (see FAISSVectorStore.rebuild_empty's docstring). Neo4j is untouched:
    the graph is keyed by document_id/chunk_index, not faiss_id, so it
    isn't invalidated by a FAISS-only rebuild.
    """
    db = SessionLocal()
    reporter = ProgressReporter(db, job_id)
    try:
        reporter.start()
        store = get_vector_store()
        store.rebuild_empty()
        # Every faiss_id in Postgres now points at a wiped index — clear
        # them all before reassigning fresh ones to the active set below.
        db.query(Chunk).update({"faiss_id": None}, synchronize_session=False)
        db.commit()

        active_chunks = (
            db.query(Chunk)
            .join(Document, Chunk.document_id == Document.document_id)
            .filter(Document.is_latest.is_(True))
            .order_by(Chunk.document_id, Chunk.chunk_index)
            .all()
        )
        for i in range(0, len(active_chunks), BATCH_SIZE):
            batch = active_chunks[i : i + BATCH_SIZE]
            for c, success, error in _reindex_chunk_batch(db, store, batch):
                reporter.advance(success=success, ref=f"{c.document_id}:{c.chunk_index}", error=error)

        from app.services.bm25_retriever import get_bm25_store
        get_bm25_store().invalidate()

        reindex_job_service.mark_completed(db, job_id)
    except Exception as exc:
        logger.error("[ChunkIndexing] Full rebuild job %s failed: %s", job_id, exc)
        reindex_job_service.mark_failed(db, job_id, str(exc))
    finally:
        db.close()
