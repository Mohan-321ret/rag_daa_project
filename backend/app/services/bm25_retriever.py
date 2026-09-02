"""
BM25 Retriever  –  Phase 8 Module 6 (Route: Exact Policy Number → BM25)
--------------------------------------------------------------------------
Sparse, term-frequency keyword search over the same chunk corpus that
FAISS indexes semantically. Vector search is good at "what's the leave
policy about" (meaning); BM25 is better at "policy 4.2" or "POL-2024-001"
(exact tokens) where semantic similarity can drown a rare, specific code
in more common surrounding text.

The index is an in-memory rank_bm25.BM25Okapi built from every chunk of
every document's LATEST version (Phase 6 versioning-consistent, mirroring
FAISS's tombstoning of stale chunks). It's rebuilt lazily on first use
after being marked dirty by `invalidate()` — call that whenever chunks are
added, changed, or removed so the next search rebuilds from PostgreSQL.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")


def _tokenize(text: str) -> List[str]:
    """Lowercase word/code tokenizer that keeps hyphenated codes (POL-2024) intact."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


@dataclass
class BM25Hit:
    document_id: str
    chunk_index: int
    text: str
    score: float
    domain_id: Optional[str] = None
    visibility: Optional[str] = None


class BM25Store:
    """In-memory BM25 index over the active (latest-version) chunk corpus."""

    def __init__(self) -> None:
        self._bm25 = None
        self._entries: List[dict] = []   # parallel to _bm25's corpus order
        self._dirty: bool = True

    def invalidate(self) -> None:
        """Mark the index stale; it will be rebuilt on the next search()."""
        self._dirty = True

    def _rebuild(self, db: Session) -> None:
        from rank_bm25 import BM25Okapi
        from app.services.storage_service import StorageService

        chunks = StorageService(db).get_all_active_chunks()
        self._entries = [
            {
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "text": c.text,
                # Domain-Aware Chunk Access Control: denormalized onto Chunk
                # at write time (see StorageService.save_chunks) — used for
                # fast in-loop filtering here. Not the authority; the final
                # filter_authorized_results() gate re-checks against
                # Document's current values regardless.
                "domain_id": str(c.domain_id) if c.domain_id else None,
                "visibility": c.visibility,
            }
            for c in chunks
        ]
        corpus = [_tokenize(e["text"]) for e in self._entries]

        if corpus:
            self._bm25 = BM25Okapi(corpus)
        else:
            self._bm25 = None

        self._dirty = False
        logger.info("[BM25Retriever] Index rebuilt | chunks=%d", len(self._entries))

    def search(
        self, db: Session, query: str, top_k: int = 5,
        filter_fn: Optional[Callable[[dict], bool]] = None,
    ) -> List[BM25Hit]:
        """
        Keyword-rank the active chunk corpus against *query*, highest first.

        filter_fn (Domain-Aware Chunk Access Control): applied while
        walking the FULL ranked list, so an unauthorized chunk ranking
        above an authorized one never crowds it out of a fixed top_k
        window — see vector_store.search()'s docstring for the same
        reasoning. get_scores() already computes over the whole corpus
        (there's no k to limit up front), so this costs nothing extra.
        """
        if self._dirty:
            self._rebuild(db)

        if self._bm25 is None or not self._entries:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            range(len(self._entries)), key=lambda i: scores[i], reverse=True
        )

        hits: List[BM25Hit] = []
        for i in ranked:
            if scores[i] <= 0:
                break   # sorted descending — nothing further scores positively
            e = self._entries[i]
            if filter_fn and not filter_fn(e):
                continue
            hits.append(BM25Hit(
                document_id=e["document_id"],
                chunk_index=e["chunk_index"],
                text=e["text"],
                score=float(scores[i]),
                domain_id=e.get("domain_id"),
                visibility=e.get("visibility"),
            ))
            if len(hits) >= top_k:
                break
        return hits


# ── Singleton ─────────────────────────────────────────────────────────────────
_store: Optional[BM25Store] = None


def get_bm25_store() -> BM25Store:
    global _store
    if _store is None:
        _store = BM25Store()
    return _store
