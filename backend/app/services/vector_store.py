"""
Vector Store Service (FAISS)
-----------------------------
Wraps FAISS for in-process vector similarity search.
Persists the index and an ID→metadata map to disk so restarts don't lose data.
"""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import faiss
import numpy as np

from app.core.config import settings
from app.services.embedding_service import embed_text, embed_batch


class FAISSVectorStore:
    """Simple FAISS-backed vector store with persistence."""

    def __init__(self, index_path: Optional[str] = None):
        self.index_path = Path(index_path or settings.faiss_index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        self.dim: int = settings.embedding_dimension
        self._index: faiss.IndexFlatIP          # inner-product (cosine after L2 norm)
        self._id_map: Dict[int, dict] = {}      # faiss_id → {text, metadata}
        self._next_id: int = 0

        self._load_or_create()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_or_create(self) -> None:
        idx_file = self.index_path.with_suffix(".index")
        meta_file = self.index_path.with_suffix(".pkl")

        if idx_file.exists() and meta_file.exists():
            self._index = faiss.read_index(str(idx_file))
            with open(meta_file, "rb") as f:
                data = pickle.load(f)
            self._id_map = data["id_map"]
            self._next_id = data["next_id"]
        else:
            self._index = faiss.IndexFlatIP(self.dim)
            self._id_map = {}
            self._next_id = 0

    def save(self) -> None:
        faiss.write_index(self._index, str(self.index_path.with_suffix(".index")))
        with open(self.index_path.with_suffix(".pkl"), "wb") as f:
            pickle.dump({"id_map": self._id_map, "next_id": self._next_id}, f)

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, text: str, metadata: dict | None = None) -> int:
        """Embed *text* and add it to the index. Returns its internal ID."""
        vector = np.array([embed_text(text)], dtype=np.float32)
        self._index.add(vector)
        fid = self._next_id
        self._id_map[fid] = {"text": text, "metadata": metadata or {}}
        self._next_id += 1
        self.save()
        return fid

    def add_batch(self, texts: List[str], metadatas: List[dict] | None = None) -> List[int]:
        """Embed and add a batch of texts. Returns their IDs."""
        vectors = np.array(embed_batch(texts), dtype=np.float32)
        return self._add_vectors(vectors, texts, metadatas)

    def add_batch_precomputed(
        self,
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[dict] | None = None,
    ) -> List[int]:
        """
        Add texts whose embeddings were ALREADY computed by the caller
        (Phase 6 incremental reindexing – avoids re-embedding). Returns their IDs.
        """
        vectors = np.array(embeddings, dtype=np.float32)
        return self._add_vectors(vectors, texts, metadatas)

    def _add_vectors(
        self,
        vectors: np.ndarray,
        texts: List[str],
        metadatas: List[dict] | None,
    ) -> List[int]:
        self._index.add(vectors)
        ids = []
        for i, text in enumerate(texts):
            fid = self._next_id
            meta = (metadatas[i] if metadatas else {}) or {}
            self._id_map[fid] = {"text": text, "metadata": meta}
            self._next_id += 1
            ids.append(fid)
        self.save()
        return ids

    # ── Incremental updates (Phase 6 – Module 3) ──────────────────────────────
    # IndexFlatIP cannot physically remove vectors without a full rebuild, so
    # stale entries are *tombstoned*: kept in the index but flagged deleted and
    # filtered out of search results. Only new/changed chunks are ever appended.

    def mark_deleted(self, faiss_ids: List[int]) -> int:
        """Tombstone the given IDs so they never surface in search results."""
        marked = 0
        for fid in faiss_ids:
            entry = self._id_map.get(int(fid))
            if entry is not None and not entry.get("deleted"):
                entry["deleted"] = True
                marked += 1
        if marked:
            self.save()
        return marked

    def update_metadata(self, faiss_id: int, metadata: dict) -> bool:
        """
        Repoint an existing (unchanged) vector at new metadata – used when a
        chunk survives a document version bump so its embedding is reused.
        """
        entry = self._id_map.get(int(faiss_id))
        if entry is None:
            return False
        entry["metadata"] = metadata or {}
        return True

    def rebuild_empty(self) -> None:
        """
        Discard every vector (including tombstoned ones) and start a fresh,
        empty index at the CURRENT settings.embedding_dimension — Admin
        Panel: Chunk Indexing Management's "full index rebuild".

        This is the one place tombstoned vectors actually stop consuming
        space (see the module comment above `mark_deleted` — normally they
        persist forever). It's also the only path that can recover from a
        dimension/model mismatch between what's on disk and the current
        config, since nothing else in this class validates that. Callers
        are responsible for re-adding every chunk that should remain
        searchable (see chunk_indexing_service.py's full-rebuild job) —
        this method only clears the index, it does not touch PostgreSQL.
        """
        self.dim = settings.embedding_dimension
        self._index = faiss.IndexFlatIP(self.dim)
        self._id_map = {}
        self._next_id = 0
        self.save()

    # ── Read ──────────────────────────────────────────────────────────────────

    def search(
        self, query: str, top_k: int = 5,
        filter_fn: Optional[Callable[[dict], bool]] = None,
    ) -> List[dict]:
        """
        Return the *top_k* most similar ACTIVE documents with scores.

        filter_fn (Domain-Aware Chunk Access Control): when given, a
        candidate's `metadata` dict must satisfy it to count toward top_k —
        applied DURING the scan, not as a post-hoc trim of a fixed-size
        window. This matters: if unauthorized documents happen to rank
        higher for this query, a fixed top_k window filtered afterward
        could silently come back empty even though enough authorized
        chunks exist further down the ranking. IndexFlatIP is a brute-force
        O(n) scan regardless of k, so when filter_fn is active we simply
        scan every active vector — there is no performance cost to doing
        so, only a correctness gain.
        """
        if self._index.ntotal == 0:
            return []
        vector = np.array([embed_text(query)], dtype=np.float32)
        # Over-fetch to compensate for tombstoned/unauthorized entries being
        # skipped; with a filter active, scan the whole (already O(n)) index.
        fetch_k = self._index.ntotal if filter_fn else min(max(top_k * 4, top_k + 10), self._index.ntotal)
        scores, indices = self._index.search(vector, fetch_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            idx_int = int(idx)
            entry = self._id_map.get(idx_int, {})
            if entry.get("deleted"):
                continue
            metadata = entry.get("metadata", {})
            if filter_fn and not filter_fn(metadata):
                continue
            results.append({
                "id": idx_int,
                "score": float(score),
                "text": entry.get("text"),
                "metadata": metadata,
            })
            if len(results) >= top_k:
                break
        return results

    @property
    def total(self) -> int:
        return self._index.ntotal

    @property
    def active_total(self) -> int:
        """Number of vectors that are NOT tombstoned."""
        deleted = sum(1 for e in self._id_map.values() if e.get("deleted"))
        return self._index.ntotal - deleted


# ── Singleton ─────────────────────────────────────────────────────────────────
_store: FAISSVectorStore | None = None


def get_vector_store() -> FAISSVectorStore:
    global _store
    if _store is None:
        _store = FAISSVectorStore()
    return _store
