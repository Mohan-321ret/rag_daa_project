"""
Concept Drift Detector  –  Phase 6 Module 3 (Step 3)
------------------------------------------------------
Detects *semantic* change between two document versions – not by comparing
text, but by comparing EMBEDDING DISTANCE:

  old chunk embeddings ──→ mean vector ─┐
                                        ├─→ cosine similarity
  new chunk embeddings ──→ mean vector ─┘

  similarity < drift_threshold  ⇒  CONCEPT CHANGED

Also performs chunk-level drift analysis: chunks that occupy the same
position in both versions but whose embeddings diverge below
`chunk_drift_threshold` are reported as individually drifted concepts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DriftResult:
    """Outcome of concept drift analysis between two document versions."""
    embedding_similarity: float          # doc-level cosine similarity (0..1)
    drift_detected: bool                 # True ⇒ concept changed
    threshold: float                     # threshold used for the doc-level flag
    drifted_chunks: List[dict] = field(default_factory=list)  # per-chunk drift info


def _mean_vector(embeddings: List[List[float]]) -> Optional[np.ndarray]:
    """Mean-pool chunk embeddings into a single document-level vector."""
    if not embeddings:
        return None
    mat = np.array(embeddings, dtype=np.float32)
    vec = mat.mean(axis=0)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def detect_drift(
    old_embeddings: Dict[int, List[float]],
    new_embeddings: Dict[int, List[float]],
    new_chunk_texts: Optional[Dict[int, str]] = None,
) -> DriftResult:
    """
    Compare embedding spaces of two document versions.

    Args:
        old_embeddings: {chunk_index: embedding} of the previous version.
        new_embeddings: {chunk_index: embedding} of the incoming version.
        new_chunk_texts: Optional {chunk_index: text} used to attach a text
                         preview to drifted-chunk reports.

    Returns:
        DriftResult with the doc-level similarity, the drift flag, and the
        list of individually drifted chunk positions.
    """
    old_doc_vec = _mean_vector(list(old_embeddings.values()))
    new_doc_vec = _mean_vector(list(new_embeddings.values()))

    if old_doc_vec is None or new_doc_vec is None:
        logger.warning("[DriftDetector] Missing embeddings – cannot assess drift.")
        return DriftResult(
            embedding_similarity=0.0,
            drift_detected=False,
            threshold=settings.drift_threshold,
        )

    doc_similarity = round(_cosine(old_doc_vec, new_doc_vec), 4)
    drift_detected = doc_similarity < settings.drift_threshold

    # ── Chunk-level drift: same position in both versions, diverging meaning ──
    drifted_chunks: List[dict] = []
    common = sorted(set(old_embeddings) & set(new_embeddings))
    for idx in common:
        sim = round(
            _cosine(
                np.array(old_embeddings[idx], dtype=np.float32),
                np.array(new_embeddings[idx], dtype=np.float32),
            ),
            4,
        )
        if sim < settings.chunk_drift_threshold:
            preview = ""
            if new_chunk_texts and idx in new_chunk_texts:
                preview = new_chunk_texts[idx][:200]
            drifted_chunks.append({
                "chunk_index": idx,
                "similarity": sim,
                "new_text_preview": preview,
            })

    drifted_chunks.sort(key=lambda d: d["similarity"])

    logger.info(
        "[DriftDetector] doc_similarity=%.4f threshold=%.2f drift=%s "
        "| drifted_chunks=%d",
        doc_similarity, settings.drift_threshold, drift_detected,
        len(drifted_chunks),
    )

    return DriftResult(
        embedding_similarity=doc_similarity,
        drift_detected=drift_detected,
        threshold=settings.drift_threshold,
        drifted_chunks=drifted_chunks[:20],
    )
