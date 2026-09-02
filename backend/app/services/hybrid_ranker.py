"""
Hybrid Ranker  –  Phase 8 Module 6 (Hybrid: "Rank results")
------------------------------------------------------------
Fuses ranked result lists from BM25, Vector, and Graph retrieval into one
ranked list using Reciprocal Rank Fusion (RRF):

    fused_score(chunk) = Σ  1 / (k + rank_in_list)
                        over every list the chunk appears in

RRF needs no score normalisation across retrievers with wildly different
scales (BM25 term-frequency scores, cosine similarities, graph match
ranks) — only each list's ORDER matters, which is why it's the standard
choice for fusing heterogeneous retrievers. A chunk that shows up near
the top of multiple lists outranks one that's merely #1 in a single list.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from app.core.config import settings

logger = logging.getLogger(__name__)


def _key(item: dict) -> tuple:
    return (item["document_id"], item["chunk_index"])


def reciprocal_rank_fusion(
    ranked_lists: Dict[str, List[dict]],
    top_k: int = 10,
    k: int | None = None,
) -> List[dict]:
    """
    Merge multiple ranked result lists into one, ordered by fused RRF score.

    Args:
        ranked_lists: {source_name: [item, ...]} where each list is already
                      sorted best-first and each item has at least
                      "document_id", "chunk_index", and "text".
        top_k:         Max number of fused results to return.
        k:              RRF smoothing constant (default: settings.hybrid_rrf_k).

    Returns:
        List of dicts: {document_id, chunk_index, text, metadata, score,
        sources: [...], contributions: {source: rank}} sorted by score desc.
    """
    rrf_k = k if k is not None else settings.hybrid_rrf_k

    fused: Dict[tuple, dict] = {}
    for source, items in ranked_lists.items():
        for rank, item in enumerate(items, start=1):
            key = _key(item)
            entry = fused.get(key)
            if entry is None:
                entry = {
                    "document_id": item["document_id"],
                    "chunk_index": item["chunk_index"],
                    "text": item.get("text", ""),
                    "metadata": item.get("metadata", {}),
                    "score": 0.0,
                    "sources": [],
                    "contributions": {},
                }
                fused[key] = entry
            entry["score"] += 1.0 / (rrf_k + rank)
            entry["sources"].append(source)
            entry["contributions"][source] = rank
            # Prefer a result that already carries full text/metadata
            if not entry["text"] and item.get("text"):
                entry["text"] = item["text"]
            if not entry["metadata"] and item.get("metadata"):
                entry["metadata"] = item["metadata"]

    ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:top_k]

    logger.info(
        "[HybridRanker] Fused %d source list(s) (%s) -> %d unique chunks -> top %d",
        len(ranked_lists), ", ".join(f"{s}={len(v)}" for s, v in ranked_lists.items()),
        len(fused), len(ranked),
    )
    return ranked
