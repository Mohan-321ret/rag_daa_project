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
from typing import Dict, List, Optional, Tuple

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

    # ── Read ──────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        """Return the *top_k* most similar documents with scores."""
        if self._index.ntotal == 0:
            return []
        vector = np.array([embed_text(query)], dtype=np.float32)
        scores, indices = self._index.search(vector, min(top_k, self._index.ntotal))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            entry = self._id_map.get(idx, {})
            results.append({
                "id": idx,
                "score": float(score),
                "text": entry.get("text"),
                "metadata": entry.get("metadata", {}),
            })
        return results

    @property
    def total(self) -> int:
        return self._index.ntotal


# ── Singleton ─────────────────────────────────────────────────────────────────
_store: FAISSVectorStore | None = None


def get_vector_store() -> FAISSVectorStore:
    global _store
    if _store is None:
        _store = FAISSVectorStore()
    return _store
