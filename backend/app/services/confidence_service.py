"""
Confidence Score Calculation Service
-------------------------------------
Calculates a deterministic confidence score (0.0 to 1.0) strictly from
retrieved document chunks and their similarity scores.

Requirements:
  1. Score is derived strictly from actual retrieved chunks/similarity scores.
  2. The LLM is NEVER asked to generate this score.
  3. Score is calculated ONLY from chunks the user is authorized to access
     (enforced upstream by ChunkAccessContext/filter_authorized_results).
  4. Output is normalized to 0.0 – 1.0.
  5. Weak or 0-retrieval yields low/0 confidence score.
  6. Configurable CONFIDENCE_THRESHOLD=0.70.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default threshold constant for modular consumption across phases
CONFIDENCE_THRESHOLD: float = getattr(settings, "confidence_threshold", 0.70)


def normalize_similarity_score(score: float, source: str = "vector") -> float:
    """
    Normalize raw similarity/retrieval score into a [0.0, 1.0] range.

    - Vector (Cosine similarity): already in [-1.0, 1.0], clamped to [0.0, 1.0].
    - BM25: non-negative term frequency score (>= 0.0), mapped smoothly via s / (s + 10.0).
    - Graph: 1.0 / rank in (0.0, 1.0].
    - Hybrid (RRF): reciprocal rank sum. Scaled smoothly to [0.0, 1.0].
    """
    if score is None:
        return 0.0

    score = float(score)

    if source == "bm25":
        if score <= 0.0:
            return 0.0
        # Smooth saturation curve for BM25 scores (10.0 is typical mid-range BM25 score)
        return min(max(score / (score + 10.0), 0.0), 1.0)

    if source == "graph":
        return min(max(score, 0.0), 1.0)

    if "hybrid" in source or "rrf" in source:
        # RRF top score for 3 sources at rank 1 with k=60 is ~3 * (1/61) = ~0.049
        # Scale RRF score to [0.0, 1.0] range using max theoretical score (~0.05)
        normalized = score * 20.0
        return min(max(normalized, 0.0), 1.0)

    # Vector / Cross-encoder / default: cosine similarity or probability
    return min(max(score, 0.0), 1.0)


def calculate_retrieval_confidence(chunks: List[dict]) -> float:
    """
    Calculate deterministic retrieval confidence score (0.0 to 1.0)
    from a list of authorized retrieved chunks.

    Formula:
      - If no chunks present: return 0.0
      - Extract normalized similarity scores for each chunk.
      - s_top = max(scores) (relevance of single best chunk)
      - s_avg = mean of top-min(len, 3) scores (consistency of evidence support)
      - Confidence = 0.70 * s_top + 0.30 * s_avg
      - Clamped to [0.0, 1.0] and rounded to 4 decimal places.

    Args:
        chunks: List of chunk dictionaries containing 'score' (and optional 'source'/'retriever_score')

    Returns:
        float: Normalized confidence score between 0.0 and 1.0
    """
    if not chunks:
        logger.info("[ConfidenceService] No retrieved chunks — confidence score set to 0.0.")
        return 0.0

    norm_scores: List[float] = []
    for chunk in chunks:
        raw_score = chunk.get("retriever_score") if chunk.get("retriever_score") is not None else chunk.get("score", 0.0)
        src = str(chunk.get("source", "vector")).lower()
        norm_score = normalize_similarity_score(raw_score, source=src)
        norm_scores.append(norm_score)

    if not norm_scores:
        return 0.0

    s_top = max(norm_scores)
    
    # Average of top 3 (or fewer if fewer chunks available)
    top_k_scores = sorted(norm_scores, reverse=True)[:min(len(norm_scores), 3)]
    s_avg = sum(top_k_scores) / len(top_k_scores)

    # Weighted confidence combination
    confidence = 0.70 * s_top + 0.30 * s_avg
    final_score = round(min(max(confidence, 0.0), 1.0), 4)

    logger.info(
        "[ConfidenceService] Computed retrieval confidence: %.4f (s_top=%.4f, s_avg=%.4f, chunks=%d)",
        final_score, s_top, s_avg, len(chunks)
    )

    return final_score


def get_confidence_level(confidence_score: float) -> str:
    """
    Categorize confidence score into human-readable level.

    Percentage ranges:
      - 80%–100% (>= 0.80) -> 'High'
      - 60%–79%  (0.60 to 0.79) -> 'Medium'
      - <60%     (< 0.60) -> 'Low'
    """
    if confidence_score >= 0.80:
        return "High"
    if confidence_score >= 0.60:
        return "Medium"
    return "Low"
