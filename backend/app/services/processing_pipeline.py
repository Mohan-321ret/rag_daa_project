"""
Processing Pipeline  –  Phase 3 Module 2 (Orchestrator)
---------------------------------------------------------
Wires all 5 steps of the intelligent document processing pipeline:

  Step 1  clean_text()         [text_cleaner]  – HTML + noise removal
  Step 2  (included in Step 1) [text_cleaner]  – page numbers, watermarks, disclaimers
  Step 3  detect_language()    [metadata_service] – auto language detection
  Step 4  chunk_document()     [chunking_service] – RecursiveCharacterTextSplitter
  Step 5  embed_chunks()       [embedding_service] – BAAI/bge or all-MiniLM
           store_chunks()      [storage_service]   – PostgreSQL chunks table
           index_in_faiss()    [vector_store]      – FAISS index

Entry point: run_processing_pipeline(document_id, raw_text, db, language_hint)

Admin Panel: Data Injection Management — `on_stage`, if given, is called at
the start and end of each named PIPELINE_STAGES step (see
app/models/ingestion_job.py) so a caller can persist real per-stage
progress (app/services/ingestion_job_service.StageReporter does exactly
this). It's optional and defaults to a no-op so the folder-watcher path
(app/services/change_monitor.py), which has no IngestionJob to update,
behaves exactly as before — this module has no idea IngestionJob exists.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.text_cleaner import clean_text
from app.services.chunking_service import chunk_document, TextChunk
from app.services.embedding_service import embed_batch
from app.services.vector_store import get_vector_store
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

StageCallback = Callable[[str, str, Optional[str]], None]


def _noop_stage(stage: str, status: str, error: Optional[str] = None) -> None:
    pass


# ── Pipeline result dataclass ─────────────────────────────────────────────────

class PipelineResult:
    """Holds the outcome of a successful pipeline run."""
    def __init__(
        self,
        document_id: str,
        cleaned_text: str,
        language: str,
        chunk_count: int,
        faiss_ids: List[int],
    ):
        self.document_id = document_id
        self.cleaned_text = cleaned_text
        self.language = language
        self.chunk_count = chunk_count
        self.faiss_ids = faiss_ids


# ── Main entry point ──────────────────────────────────────────────────────────

def run_processing_pipeline(
    document_id: str,
    raw_text: str,
    db: Session,
    language_hint: Optional[str] = None,
    on_stage: Optional[StageCallback] = None,
) -> PipelineResult:
    """
    Execute the full 5-step preprocessing pipeline for a document.

    Args:
        document_id:    The DOC_xxxx identifier (already saved in DB).
        raw_text:       Raw extracted text from document_loader / OCR.
        db:             Active SQLAlchemy session (shared with the request).
        language_hint:  Optional ISO 639-1 language code from user input.
        on_stage:       Optional StageCallback — see module docstring.

    Returns:
        PipelineResult with summary statistics.

    Raises:
        RuntimeError: If any critical step fails.
    """
    on_stage = on_stage or _noop_stage
    storage = StorageService(db)
    logger.info(
        "[Pipeline] Starting processing pipeline for document %s", document_id
    )

    # ─── Step 1 & 2: Text Cleaning + Noise Removal ────────────────────────────
    # One function call does both (see text_cleaner.py) — reported as two
    # stages since the spec's pipeline diagram lists them separately, both
    # closing at the same moment.
    logger.info("[Pipeline] Step 1+2 | Cleaning text and removing noise...")
    on_stage("text_cleaning", "running")
    on_stage("noise_removal", "running")
    try:
        cleaned = clean_text(raw_text)
        if not cleaned.strip():
            raise RuntimeError(
                "Text cleaning produced empty output. "
                "The document may contain only images or unsupported content."
            )
    except Exception as exc:
        on_stage("text_cleaning", "failed", str(exc))
        on_stage("noise_removal", "failed", str(exc))
        raise
    on_stage("text_cleaning", "completed")
    on_stage("noise_removal", "completed")
    logger.info(
        "[Pipeline] Step 1+2 done | %d -> %d chars", len(raw_text), len(cleaned)
    )

    # ─── Step 3: Language Detection ───────────────────────────────────────────
    on_stage("language_detection", "running")
    if language_hint:
        language = language_hint
        logger.info("[Pipeline] Step 3 | Language supplied by user: %s", language)
    else:
        from app.services.metadata_service import detect_language
        language = detect_language(cleaned)
        logger.info("[Pipeline] Step 3 | Language auto-detected: %s", language)
    on_stage("language_detection", "completed")

    # ─── Step 4: Semantic Chunking ────────────────────────────────────────────
    logger.info("[Pipeline] Step 4 | Chunking document...")
    on_stage("chunking", "running")
    try:
        chunks: List[TextChunk] = chunk_document(cleaned)
    except Exception as exc:
        on_stage("chunking", "failed", str(exc))
        raise

    if not chunks:
        logger.warning(
            "[Pipeline] No chunks produced for document %s – skipping embedding.",
            document_id,
        )
        on_stage("chunking", "completed")
        for stage in ("embedding", "vector_index"):
            on_stage(stage, "skipped")
        storage.update_processing_status(document_id, "indexed")
        on_stage("postgres_metadata", "completed")
        on_stage("neo4j", "skipped")
        return PipelineResult(
            document_id=document_id,
            cleaned_text=cleaned,
            language=language,
            chunk_count=0,
            faiss_ids=[],
        )
    on_stage("chunking", "completed")

    logger.info("[Pipeline] Step 4 done | %d chunks produced", len(chunks))

    # ─── Step 5: Embedding Generation ────────────────────────────────────────
    logger.info("[Pipeline] Step 5 | Generating embeddings for %d chunks...", len(chunks))
    on_stage("embedding", "running")
    chunk_texts = [c.text for c in chunks]
    try:
        embeddings: List[List[float]] = embed_batch(chunk_texts)
    except Exception as exc:
        on_stage("embedding", "failed", str(exc))
        raise
    on_stage("embedding", "completed")
    logger.info("[Pipeline] Step 5 | Embeddings generated (dim=%d)", len(embeddings[0]) if embeddings else 0)

    # ─── Step 5: Index in FAISS ───────────────────────────────────────────────
    logger.info("[Pipeline] Step 5 | Indexing chunks in FAISS...")
    on_stage("vector_index", "running")
    vector_store = get_vector_store()
    # Domain-Aware Chunk Access Control: domain_id/visibility ride along in
    # FAISS metadata so vector search can filter unauthorized candidates
    # DURING the scan (fast path) — see chunk_access_service.py. This is an
    # optimization only; the authoritative check re-verifies against
    # Postgres regardless, so stale/missing values here fail closed, not open.
    parent_doc = storage.get_by_document_id(document_id)
    doc_domain_id = str(parent_doc.domain_id) if parent_doc and parent_doc.domain_id else None
    doc_visibility = parent_doc.visibility if parent_doc else None
    chunk_metadata = [
        {
            "document_id": document_id,
            "chunk_index": c.index,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "word_count": c.word_count,
            "language": language,
            "domain_id": doc_domain_id,
            "visibility": doc_visibility,
        }
        for c in chunks
    ]
    try:
        faiss_ids: List[int] = vector_store.add_batch(chunk_texts, chunk_metadata)
    except Exception as exc:
        on_stage("vector_index", "failed", str(exc))
        raise
    on_stage("vector_index", "completed")
    logger.info("[Pipeline] Step 5 | %d chunks indexed in FAISS", len(faiss_ids))

    # ─── Step 5: Persist chunks to PostgreSQL ────────────────────────────────
    logger.info("[Pipeline] Step 5 | Persisting chunks to PostgreSQL...")
    on_stage("postgres_metadata", "running")
    chunks_with_embeddings: List[Tuple] = list(
        zip(chunks, embeddings, faiss_ids)
    )
    try:
        storage.save_chunks(document_id, chunks_with_embeddings)
    except Exception as exc:
        on_stage("postgres_metadata", "failed", str(exc))
        raise
    on_stage("postgres_metadata", "completed")

    # ─── Step 5: Populate BM25 + Knowledge Graph indexes (Phase 8 – Module 6) ─
    # Keeps the "exact policy number" (BM25) and "relationship" (graph) routes
    # in sync with every new document, alongside the FAISS vector index above.
    from app.services.bm25_retriever import get_bm25_store
    get_bm25_store().invalidate()

    on_stage("neo4j", "running")
    from app.services.graph_retriever import get_graph_retriever
    from app.services.ner_service import extract_entities
    graph_retriever = get_graph_retriever()
    for c in chunks:
        graph_retriever.index_chunk_entities(
            document_id, c.index, extract_entities(c.text),
            domain_id=doc_domain_id, visibility=doc_visibility,
        )
    # index_chunk_entities() never raises — it no-ops when Neo4j is
    # unreachable (see graph_retriever.py) — so this always "completes";
    # there is no distinct signal here for "Neo4j was down", only server logs.
    on_stage("neo4j", "completed")

    # ─── Mark document as fully indexed ──────────────────────────────────────
    storage.update_processing_status(document_id, "indexed")
    logger.info(
        "[Pipeline] Pipeline complete for %s | chunks=%d language=%s",
        document_id, len(chunks), language,
    )

    return PipelineResult(
        document_id=document_id,
        cleaned_text=cleaned,
        language=language,
        chunk_count=len(chunks),
        faiss_ids=faiss_ids,
    )
