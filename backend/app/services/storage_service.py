"""
Storage Service  –  Phase 3 Module 2 (Step 5 persistence)
----------------------------------------------------------
Persists the extracted document data (text + metadata) and semantic chunks
(text + embedding + FAISS ID) to PostgreSQL.
NEVER stores the original binary file.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.document import ExtractedDocumentData

logger = logging.getLogger(__name__)


class StorageService:
    """Handles all PostgreSQL persistence for the ingestion pipeline."""

    def __init__(self, db: Session):
        self.db = db

    # ── Document ──────────────────────────────────────────────────────────────

    def save_document(self, data: ExtractedDocumentData) -> Document:
        """
        Persist a new document record to the `documents` table.

        Args:
            data: DTO carrying extracted text and metadata.

        Returns:
            The persisted Document ORM object (with DB-generated fields).

        Raises:
            RuntimeError: On any database error.
        """
        logger.info(
            "[StorageService] Saving document to PostgreSQL | id=%s",
            data.document_id,
        )

        document = Document(
            document_id=data.document_id,
            filename=data.filename,
            original_filename=data.original_filename,
            document_type=data.document_type,
            file_extension=data.file_extension,
            author=data.author,
            title=data.title,
            department=data.department,
            permissions=data.permissions,
            language=data.language,
            domain_id=data.domain_id,
            visibility=data.visibility,
            owner_id=data.owner_id,
            uploaded_by_id=data.uploaded_by_id,
            upload_date=data.upload_date,
            ocr_used=data.ocr_used,
            word_count=data.word_count,
            character_count=data.character_count,
            extraction_duration_s=data.extraction_duration_s,
            extracted_text=data.extracted_text,
            processing_status="processing",   # will be updated to 'indexed' after chunking
        )

        try:
            self.db.add(document)
            self.db.commit()
            self.db.refresh(document)
            logger.info(
                "[StorageService] ✅ Document saved | id=%s words=%d",
                document.document_id, document.word_count,
            )
            return document

        except Exception as exc:
            self.db.rollback()
            logger.error(
                "[StorageService] ❌ DB commit failed for %s: %s",
                data.document_id, exc,
            )
            raise RuntimeError(
                f"Database error while saving document '{data.document_id}': {exc}"
            ) from exc

    # ── Chunks (Phase 3 – Step 5) ─────────────────────────────────────────────

    def save_chunks(
        self,
        document_id: str,
        chunks_with_embeddings: List[Tuple],
    ) -> List[Chunk]:
        """
        Persist all semantic chunks for a document.

        Args:
            document_id: Human-readable DOC_xxxx identifier.
            chunks_with_embeddings: List of (TextChunk, embedding: list[float], faiss_id: int).

        Returns:
            List of persisted Chunk ORM objects.

        Raises:
            RuntimeError: On any database error.

        Domain-aware traceability: every chunk is stamped with its parent
        Document's version/domain_id/visibility, looked up once here — the
        single propagation point, so callers (processing_pipeline.py,
        incremental_indexer.py) don't each need to know about it.
        """
        logger.info(
            "[StorageService] Saving %d chunks for document %s",
            len(chunks_with_embeddings), document_id,
        )

        parent = self.get_by_document_id(document_id)
        now = datetime.now(timezone.utc)

        chunk_rows: list[Chunk] = []
        for text_chunk, embedding, faiss_id in chunks_with_embeddings:
            chunk_rows.append(Chunk(
                document_id=document_id,
                chunk_index=text_chunk.index,
                text=text_chunk.text,
                char_start=text_chunk.char_start,
                char_end=text_chunk.char_end,
                word_count=text_chunk.word_count,
                embedding=json.dumps(embedding),   # serialise as JSON text
                faiss_id=faiss_id,
                document_version=parent.version if parent else None,
                domain_id=parent.domain_id if parent else None,
                visibility=parent.visibility if parent else None,
                # Chunk Indexing Management: this chunk is created WITH a
                # live FAISS vector already (faiss_id above), so it starts
                # 'indexed' the moment it exists — index_status's column
                # default already covers the status half of that, but
                # indexed_at has no column default (it's meaningful only
                # once a vector exists, not at row-creation in general), so
                # it must be stamped explicitly here, same as every reindex
                # operation stamps it in chunk_indexing_service.py.
                indexed_at=now,
            ))

        try:
            self.db.bulk_save_objects(chunk_rows)
            self.db.commit()
            logger.info(
                "[StorageService] ✅ %d chunks saved for document %s",
                len(chunk_rows), document_id,
            )
            return chunk_rows

        except Exception as exc:
            self.db.rollback()
            logger.error(
                "[StorageService] ❌ Failed to save chunks for %s: %s",
                document_id, exc,
            )
            raise RuntimeError(
                f"Database error while saving chunks for '{document_id}': {exc}"
            ) from exc

    def get_chunks(self, document_id: str) -> List[Chunk]:
        """Retrieve all chunks for a document, ordered by chunk_index."""
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .all()
        )

    def get_all_active_chunks(self) -> List[Chunk]:
        """
        Return every chunk belonging to a document's LATEST version
        (Phase 6 versioning: is_latest=True). Used to (re)build the BM25
        corpus and the co-occurrence graph so stale/superseded chunks never
        surface in keyword or relationship search (consistent with FAISS,
        which tombstones them).
        """
        return (
            self.db.query(Chunk)
            .join(Document, Chunk.document_id == Document.document_id)
            .filter(Document.is_latest.is_(True))
            .order_by(Chunk.document_id, Chunk.chunk_index)
            .all()
        )

    def get_chunk_by_index(self, document_id: str, chunk_index: int) -> Chunk | None:
        """Fetch a single chunk by its (document_id, chunk_index) key."""
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id, Chunk.chunk_index == chunk_index)
            .first()
        )

    def get_chunk_count(self, document_id: str) -> int:
        """Return the number of chunks stored for a document."""
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .count()
        )

    # ── Read (documents) ──────────────────────────────────────────────────────

    def get_by_document_id(self, document_id: str) -> Document | None:
        """Fetch a document record by its human-readable document_id."""
        return (
            self.db.query(Document)
            .filter(Document.document_id == document_id)
            .first()
        )

    def list_documents(self, skip: int = 0, limit: int = 50) -> list[Document]:
        """Return a paginated list of all documents."""
        return (
            self.db.query(Document)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    # ── Status updates ────────────────────────────────────────────────────────

    def update_processing_status(self, document_id: str, status: str) -> None:
        """
        Update a document's processing_status field.

        Args:
            document_id: Human-readable DOC_xxxx identifier.
            status: One of 'processing' | 'indexed' | 'failed'.
        """
        doc = self.get_by_document_id(document_id)
        if doc:
            doc.processing_status = status
            try:
                self.db.commit()
                logger.info(
                    "[StorageService] Status updated | id=%s status=%s",
                    document_id, status,
                )
            except Exception:
                self.db.rollback()

    def mark_failed(self, document_id: str, reason: str) -> None:
        """
        Set a document's processing_status to 'failed'.
        Used in the error path to keep an audit trail.
        """
        logger.warning(
            "[StorageService] Marking document as failed | id=%s reason=%s",
            document_id, reason,
        )
        self.update_processing_status(document_id, "failed")

