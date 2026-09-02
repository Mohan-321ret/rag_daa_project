"""
Duplicate Removal  –  Phase 9 Module 7 (Step 1: Duplicate Removal)
------------------------------------------------------------------------
Retrieved chunks often overlap:
  - Adjacent chunks share text because of chunk_overlap (Phase 3 chunking)
  - The Hybrid route (Phase 8) can resurface the SAME passage worded
    slightly differently across BM25/vector/graph phrasing, or two chunks
    from different documents that simply restate the same policy.

Exact duplicates are removed by a normalised-text hash. Near-duplicates are
removed via Jaccard similarity over word shingles (n-grams) — cheap,
deterministic, no extra model call needed before the (more expensive)
cross-encoder step. When two chunks collide, the higher-scored one is kept.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+")


@dataclass
class DedupResult:
    results: List[dict] = field(default_factory=list)
    original_count: int = 0
    removed_count: int = 0


def _shingles(text: str, k: int) -> set:
    words = _WORD_RE.findall((text or "").lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def remove_duplicates(
    results: List[dict],
    threshold: Optional[float] = None,
    shingle_size: Optional[int] = None,
) -> DedupResult:
    """
    Drop exact and near-duplicate chunks from a retrieval result list.

    Args:
        results:       Retrieved chunks (each needs at least "text" and "score").
        threshold:      Jaccard similarity above which two chunks are treated as
                        duplicates (default: settings.dedup_similarity_threshold).
        shingle_size:   Word n-gram size for shingling (default: settings.dedup_shingle_size).

    Returns:
        DedupResult with the deduplicated list (highest-scored survivor kept),
        preserving relative score order.
    """
    threshold = threshold if threshold is not None else settings.dedup_similarity_threshold
    shingle_size = shingle_size if shingle_size is not None else settings.dedup_shingle_size

    if not results:
        return DedupResult(results=[], original_count=0, removed_count=0)

    ordered = sorted(results, key=lambda r: r.get("score", 0.0), reverse=True)

    kept: List[dict] = []
    kept_shingles: List[set] = []
    seen_hashes: set = set()

    for r in ordered:
        text = (r.get("text") or "").strip()
        norm_hash = re.sub(r"\s+", " ", text.lower())

        if norm_hash and norm_hash in seen_hashes:
            continue  # exact duplicate

        sh = _shingles(text, shingle_size)
        if any(_jaccard(sh, ks) >= threshold for ks in kept_shingles):
            continue  # near-duplicate

        kept.append(r)
        kept_shingles.append(sh)
        if norm_hash:
            seen_hashes.add(norm_hash)

    removed = len(results) - len(kept)
    if removed:
        logger.info(
            "[Dedup] Removed %d duplicate/near-duplicate chunk(s) of %d.",
            removed, len(results),
        )
    return DedupResult(results=kept, original_count=len(results), removed_count=removed)
