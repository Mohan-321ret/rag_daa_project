"""
Knowledge Evolution Engine  –  Phase 6 Module 3 (Orchestrator)
----------------------------------------------------------------
Research contribution: keeps the knowledge base *fresh* as documents evolve.

Wires all 5 steps of the evolution pipeline:

  Step 1  Change Monitor        – detect new vs. updated vs. unchanged uploads
                                  (content-hash matching on filename lineage)
  Step 2  Version Comparator    – old vs. new text → structured diff
  Step 3  Concept Drift         – embedding-distance comparison (not text!)
  Step 4  Conflict Detection    – contradicting factual statements flagged
  Step 5  Incremental Reindex   – only changed chunks re-embedded into FAISS

Entry point: process_document(db, doc_data, …) – evolution-aware replacement
for the plain "save + full pipeline" ingestion path. Every decision is
recorded as a DocumentChange event (the evolution timeline).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_change import DocumentChange
from app.schemas.document import ExtractedDocumentData
from app.services.chunking_service import chunk_document
from app.services.conflict_detector import detect_conflicts
from app.services.drift_detector import detect_drift
from app.services.incremental_indexer import reindex_incrementally
from app.services.processing_pipeline import StageCallback, run_processing_pipeline
from app.services.storage_service import StorageService
from app.services.text_cleaner import clean_text
from app.services.version_comparator import compare_versions

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_content_hash(text: str) -> str:
    """SHA-256 fingerprint of a document's extracted text."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _new_event_id() -> str:
    return f"EVT_{uuid.uuid4().hex[:10].upper()}"


def find_previous_version(
    db: Session, original_filename: str
) -> Optional[Document]:
    """
    Step 1 (upload watch): find the latest existing version of a document
    identified by its original filename.
    """
    return (
        db.query(Document)
        .filter(
            Document.original_filename == original_filename,
            Document.is_latest.is_(True),
        )
        .order_by(Document.version.desc())
        .first()
    )


def get_version_history(db: Session, document_id: str) -> list[Document]:
    """All versions sharing the given document's filename lineage, oldest first."""
    doc = (
        db.query(Document)
        .filter(Document.document_id == document_id)
        .first()
    )
    if not doc:
        return []
    return (
        db.query(Document)
        .filter(Document.original_filename == doc.original_filename)
        .order_by(Document.version.asc(), Document.created_at.asc())
        .all()
    )


# ── Main entry point (evolution-aware ingestion) ──────────────────────────────

def process_document(
    db: Session,
    doc_data: ExtractedDocumentData,
    language_hint: Optional[str] = None,
    source: str = "upload",
    on_stage: Optional[StageCallback] = None,
) -> dict:
    """
    Evolution-aware persistence + processing for an incoming document.

    Decides between three paths:
      unchanged     – identical content already indexed → skip entirely
      new_document  – first sighting of this file → full processing pipeline
      new_version   – filename known, content changed → evolution pipeline
                      (diff → drift → conflicts → incremental reindex)

    Returns a summary dict:
      {action, document, event_id, chunk_count, language, evolution?}
    """
    storage = StorageService(db)
    content_hash = compute_content_hash(doc_data.extracted_text)
    previous = find_previous_version(db, doc_data.original_filename)

    # ── Path 1: identical re-upload → nothing to do ──────────────────────────
    if previous is not None and previous.content_hash == content_hash:
        logger.info(
            "[Evolution] '%s' unchanged (hash match with %s) – skipping.",
            doc_data.original_filename, previous.document_id,
        )
        event = _record_event(
            db,
            change_type="unchanged",
            filename=doc_data.original_filename,
            old_document_id=previous.document_id,
            new_document_id=previous.document_id,
            version_from=previous.version,
            version_to=previous.version,
            source=source,
        )
        return {
            "action": "unchanged",
            "document": previous,
            "event_id": event.event_id,
            "chunk_count": storage.get_chunk_count(previous.document_id),
            "language": previous.language,
        }

    # ── Persist the incoming document with version metadata ──────────────────
    saved = storage.save_document(doc_data)
    saved.content_hash = content_hash
    if previous is not None:
        saved.version = (previous.version or 1) + 1
        saved.previous_version_id = previous.document_id
        previous.is_latest = False
        # Admin Panel: Chunk Indexing Management — the superseded version's
        # chunks are now "stale" (still indexed, but belong to a document
        # that's no longer the latest). Only flips currently-'indexed' rows
        # so an in-flight reindex job's 'pending'/'failed' state on these
        # same chunks (unlikely but possible) isn't silently overwritten.
        from app.models.chunk import Chunk
        db.query(Chunk).filter(
            Chunk.document_id == previous.document_id, Chunk.index_status == "indexed",
        ).update({"index_status": "stale"}, synchronize_session=False)
    saved.is_latest = True
    db.commit()

    # ── Path 2: brand-new document → normal full pipeline ────────────────────
    if previous is None:
        chunk_count, language = 0, saved.language
        try:
            pipeline_result = run_processing_pipeline(
                document_id=saved.document_id,
                raw_text=doc_data.extracted_text,
                db=db,
                language_hint=language_hint,
                on_stage=on_stage,
            )
            chunk_count = pipeline_result.chunk_count
            language = pipeline_result.language
        except Exception as exc:
            logger.error(
                "[Evolution] Pipeline failed for new document %s: %s",
                saved.document_id, exc,
            )
            storage.mark_failed(saved.document_id, str(exc))

        event = _record_event(
            db,
            change_type="new_document",
            filename=saved.original_filename,
            new_document_id=saved.document_id,
            version_to=saved.version,
            source=source,
        )
        return {
            "action": "new_document",
            "document": saved,
            "event_id": event.event_id,
            "chunk_count": chunk_count,
            "language": language,
        }

    # ── Path 3: new version of a known document → evolution pipeline ─────────
    try:
        return _process_new_version(
            db, previous, saved, language_hint=language_hint, source=source, on_stage=on_stage,
        )
    except Exception as exc:
        logger.error(
            "[Evolution] Evolution pipeline failed for %s → %s: %s",
            previous.document_id, saved.document_id, exc,
        )
        storage.mark_failed(saved.document_id, str(exc))
        return {
            "action": "new_version",
            "document": saved,
            "event_id": None,
            "chunk_count": 0,
            "language": saved.language,
            "error": str(exc),
        }


# ── The 5-step evolution pipeline for version updates ─────────────────────────

def _process_new_version(
    db: Session,
    old_doc: Document,
    new_doc: Document,
    language_hint: Optional[str],
    source: str,
    on_stage: Optional[StageCallback] = None,
) -> dict:
    from app.services.processing_pipeline import _noop_stage
    on_stage = on_stage or _noop_stage
    storage = StorageService(db)
    logger.info(
        "[Evolution] 🔄 New version detected: %s v%d → %s v%d ('%s')",
        old_doc.document_id, old_doc.version,
        new_doc.document_id, new_doc.version,
        new_doc.original_filename,
    )

    # ── Prepare text + chunks (same cleaning as the normal pipeline) ─────────
    # A new-VERSION upload reports the same named stages a new-DOCUMENT
    # upload does, even though the underlying work here (diff/drift/conflict
    # detection) is evolution-engine-specific and has no stage of its own in
    # the spec's pipeline diagram — those extra steps aren't reported.
    on_stage("text_cleaning", "running")
    on_stage("noise_removal", "running")
    cleaned = clean_text(new_doc.extracted_text or "")
    on_stage("text_cleaning", "completed")
    on_stage("noise_removal", "completed")

    on_stage("language_detection", "running")
    if language_hint:
        language = language_hint
    else:
        from app.services.metadata_service import detect_language
        language = detect_language(cleaned) if cleaned.strip() else (new_doc.language or "en")
    on_stage("language_detection", "completed")

    on_stage("chunking", "running")
    new_chunks = chunk_document(cleaned)
    on_stage("chunking", "completed")

    # ── Step 2: Version Comparator (old text vs new text → diff) ─────────────
    diff = compare_versions(
        old_doc.extracted_text or "",
        new_doc.extracted_text or "",
        old_label=f"{old_doc.document_id} (v{old_doc.version})",
        new_label=f"{new_doc.document_id} (v{new_doc.version})",
    )

    # ── Step 5: Incremental Reindexing (only changed chunks embedded) ────────
    reindex = reindex_incrementally(
        db,
        old_document_id=old_doc.document_id,
        new_document_id=new_doc.document_id,
        new_chunks=new_chunks,
        language=language,
        on_stage=on_stage,
    )

    # Drop the superseded version's presence from the Knowledge Graph (Phase 8 –
    # Module 6): only the latest version should surface via the graph route.
    from app.services.graph_retriever import get_graph_retriever
    get_graph_retriever().remove_document(old_doc.document_id)

    # ── Step 3: Concept Drift Detection (embedding distance, not text) ───────
    drift = detect_drift(
        reindex.old_embeddings,
        reindex.new_embeddings,
        new_chunk_texts={c.index: c.text for c in new_chunks},
    )

    # ── Step 4: Conflict Detection (contradicting factual statements) ────────
    conflict_result = detect_conflicts(
        old_doc.extracted_text or "",
        new_doc.extracted_text or "",
    )

    storage.update_processing_status(new_doc.document_id, "indexed")

    # ── Record the evolution event ───────────────────────────────────────────
    event = _record_event(
        db,
        change_type="new_version",
        filename=new_doc.original_filename,
        old_document_id=old_doc.document_id,
        new_document_id=new_doc.document_id,
        version_from=old_doc.version,
        version_to=new_doc.version,
        source=source,
        lines_added=diff.lines_added,
        lines_removed=diff.lines_removed,
        lines_modified=diff.lines_modified,
        text_similarity=diff.text_similarity,
        unified_diff=diff.unified_diff,
        embedding_similarity=drift.embedding_similarity,
        drift_detected=drift.drift_detected,
        drifted_chunks=json.dumps(drift.drifted_chunks),
        conflict_count=conflict_result.count,
        conflicts=json.dumps(conflict_result.to_dicts()),
        chunks_unchanged=reindex.chunks_unchanged,
        chunks_added=reindex.chunks_added,
        chunks_removed=reindex.chunks_removed,
        embeddings_reused=reindex.embeddings_reused,
        embeddings_computed=reindex.embeddings_computed,
    )

    logger.info(
        "[Evolution] ✅ %s v%d → v%d | similarity(text)=%.3f "
        "similarity(embedding)=%.3f drift=%s conflicts=%d "
        "| reindex: reused=%d computed=%d removed=%d",
        new_doc.original_filename, old_doc.version, new_doc.version,
        diff.text_similarity, drift.embedding_similarity,
        drift.drift_detected, conflict_result.count,
        reindex.embeddings_reused, reindex.embeddings_computed,
        reindex.chunks_removed,
    )

    return {
        "action": "new_version",
        "document": new_doc,
        "event_id": event.event_id,
        "chunk_count": len(new_chunks),
        "language": language,
        "evolution": {
            "event_id": event.event_id,
            "diff": {
                "lines_added": diff.lines_added,
                "lines_removed": diff.lines_removed,
                "lines_modified": diff.lines_modified,
                "text_similarity": diff.text_similarity,
            },
            "drift": {
                "embedding_similarity": drift.embedding_similarity,
                "threshold": drift.threshold,
                "concept_changed": drift.drift_detected,
                "drifted_chunks": len(drift.drifted_chunks),
            },
            "conflicts": conflict_result.to_dicts(),
            "reindex": {
                "chunks_unchanged": reindex.chunks_unchanged,
                "chunks_added": reindex.chunks_added,
                "chunks_removed": reindex.chunks_removed,
                "embeddings_reused": reindex.embeddings_reused,
                "embeddings_computed": reindex.embeddings_computed,
            },
        },
    }


# ── Ad-hoc comparison (API: POST /evolution/compare) ──────────────────────────

def compare_documents(db: Session, old_document_id: str, new_document_id: str) -> dict:
    """
    Run Steps 2–4 between any two already-ingested documents (no reindexing).
    """
    storage = StorageService(db)
    old_doc = storage.get_by_document_id(old_document_id)
    new_doc = storage.get_by_document_id(new_document_id)
    if old_doc is None or new_doc is None:
        missing = old_document_id if old_doc is None else new_document_id
        raise ValueError(f"Document '{missing}' not found.")

    diff = compare_versions(
        old_doc.extracted_text or "",
        new_doc.extracted_text or "",
        old_label=old_document_id,
        new_label=new_document_id,
    )

    def _load_embeddings(document_id: str) -> dict[int, list[float]]:
        embeddings: dict[int, list[float]] = {}
        for row in storage.get_chunks(document_id):
            if row.embedding:
                try:
                    embeddings[row.chunk_index] = json.loads(row.embedding)
                except (ValueError, TypeError):
                    pass
        return embeddings

    drift = detect_drift(
        _load_embeddings(old_document_id),
        _load_embeddings(new_document_id),
    )
    conflict_result = detect_conflicts(
        old_doc.extracted_text or "",
        new_doc.extracted_text or "",
    )

    return {
        "old_document_id": old_document_id,
        "new_document_id": new_document_id,
        "diff": {
            "lines_added": diff.lines_added,
            "lines_removed": diff.lines_removed,
            "lines_modified": diff.lines_modified,
            "text_similarity": diff.text_similarity,
            "unified_diff": diff.unified_diff,
        },
        "drift": {
            "embedding_similarity": drift.embedding_similarity,
            "threshold": drift.threshold,
            "concept_changed": drift.drift_detected,
            "drifted_chunks": drift.drifted_chunks,
        },
        "conflicts": conflict_result.to_dicts(),
        "conflict_count": conflict_result.count,
    }


# ── Event persistence ─────────────────────────────────────────────────────────

def _record_event(db: Session, **fields) -> DocumentChange:
    """Persist one DocumentChange row; never lets logging kill the request."""
    event = DocumentChange(event_id=_new_event_id(), **fields)
    try:
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "[Evolution] 📝 Event recorded | %s type=%s file=%s",
            event.event_id, event.change_type, event.filename,
        )
    except Exception as exc:
        db.rollback()
        logger.error("[Evolution] Failed to record change event: %s", exc)
    return event
