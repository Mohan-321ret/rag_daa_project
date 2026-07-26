"""
Embedding Service
-----------------
Loads a Sentence Transformers model and exposes encode helpers.
The model is loaded once and cached for the lifetime of the process.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer
from app.core.config import settings


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load and cache the Sentence Transformers model."""
    return SentenceTransformer(settings.embedding_model)


def embed_text(text: str) -> List[float]:
    """Return a single embedding vector for *text*."""
    model = _get_model()
    vector: np.ndarray = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Return embedding vectors for a list of texts."""
    model = _get_model()
    vectors: np.ndarray = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return vectors.tolist()
