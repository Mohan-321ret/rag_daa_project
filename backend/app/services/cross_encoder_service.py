"""
Cross Encoder Ranking  –  Phase 9 Module 7 (Step 2: Cross Encoder Ranking)
------------------------------------------------------------------------------
The retrievers in Phase 8 (BM25 term-frequency, FAISS cosine similarity,
graph co-occurrence rank, RRF fusion) each score relevance on their own
scale using cheap signals. A cross-encoder scores each (query, chunk) pair
JOINTLY through a small transformer — much more precise than a bi-encoder
or keyword match, at the cost of being too slow to run over the whole
corpus (hence it re-ranks only the small candidate set retrieval already
narrowed down, rather than replacing retrieval).

Model is loaded once and cached, mirroring embedding_service's pattern.
Fails soft: if the model can't be loaded (e.g. no network for the first
download), reranking is skipped and the original retrieval order is kept.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    results: List[dict] = field(default_factory=list)
    applied: bool = False   # False if the cross-encoder was skipped/unavailable


@lru_cache(maxsize=1)
def _get_cross_encoder():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.cross_encoder_model)


def rerank(query: str, results: List[dict]) -> RerankResult:
    """
    Re-score and re-sort *results* by cross-encoder relevance to *query*.

    Each result's original retriever score is preserved under
    "retriever_score"; "score" is overwritten with the cross-encoder's
    (query, chunk) relevance score, which becomes the authoritative score
    for the rest of the Context Fusion pipeline (compression, citations).
    """
    if not results:
        return RerankResult(results=[], applied=False)

    if not settings.cross_encoder_enabled:
        return RerankResult(results=results, applied=False)

    try:
        model = _get_cross_encoder()
        pairs = [(query, (r.get("text") or "")) for r in results]
        scores = model.predict(pairs)
    except Exception as exc:
        logger.warning(
            "[CrossEncoder] Reranking unavailable (%s) – keeping retrieval order.", exc
        )
        return RerankResult(results=results, applied=False)

    reranked: List[dict] = []
    for r, score in zip(results, scores):
        item = dict(r)
        item["retriever_score"] = r.get("score", 0.0)
        item["score"] = float(score)
        reranked.append(item)

    reranked.sort(key=lambda r: r["score"], reverse=True)

    logger.info(
        "[CrossEncoder] Reranked %d chunk(s) with %s.",
        len(reranked), settings.cross_encoder_model,
    )
    return RerankResult(results=reranked, applied=True)
