"""
Context Fusion Engine  –  Phase 9 Module 7 (Orchestrator)
------------------------------------------------------------------
Retrieved chunks (Phase 8's vector/BM25/graph/hybrid router) often overlap.
This module fuses them into one optimized context block:

  Retrieved Chunks
       ↓
  Step 1  Duplicate Removal     [dedup_service]      – drop exact/near-dup chunks
       ↓
  Step 2  Cross Encoder Ranking [cross_encoder_service] – precise (query,chunk) rescoring
       ↓
  Step 3  Context Compression   [context_compressor]  – extractive trim + budget fit
       ↓
  Step 4  Prompt Builder        [prompt_builder]      – assemble the final prompt
       ↓
  Output: Optimized Context

Entry point: fuse_context(query, results) -> ContextFusionResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from app.services.context_compressor import compress_context
from app.services.cross_encoder_service import rerank
from app.services.dedup_service import remove_duplicates
from app.services.prompt_builder import BuiltPrompt, build_prompt

logger = logging.getLogger(__name__)


@dataclass
class ContextFusionResult:
    results: List[dict] = field(default_factory=list)
    prompt: BuiltPrompt = None
    stats: Dict = field(default_factory=dict)


def fuse_context(query: str, results: List[dict]) -> ContextFusionResult:
    """
    Run the full Context Fusion pipeline over a retrieval result list and
    return the optimized context plus the ready-to-send prompt.
    """
    chunks_in = len(results)
    chars_in = sum(len(r.get("text") or "") for r in results)

    # ─── Step 1: Duplicate Removal ─────────────────────────────────────────────
    dedup_result = remove_duplicates(results)

    # ─── Step 2: Cross Encoder Ranking ─────────────────────────────────────────
    rerank_result = rerank(query, dedup_result.results)

    # ─── Step 3: Context Compression ───────────────────────────────────────────
    compression_result = compress_context(query, rerank_result.results)

    # ─── Step 4: Prompt Builder → Output: Optimized Context ───────────────────
    built = build_prompt(query, compression_result.results)

    stats = {
        "chunks_in": chunks_in,
        "chars_in": chars_in,
        "duplicates_removed": dedup_result.removed_count,
        "chunks_after_dedup": len(dedup_result.results),
        "cross_encoder_applied": rerank_result.applied,
        "chunks_dropped_for_budget": compression_result.dropped_for_budget,
        "chunks_out": len(compression_result.results),
        "chars_out": compression_result.chars_out,
        "compression_ratio": compression_result.compression_ratio,
    }
    logger.info(
        "[ContextFusion] chunks %d->%d (dedup -%d, budget -%d) | chars %d->%d (ratio=%.2f) | cross_encoder=%s",
        stats["chunks_in"], stats["chunks_out"],
        stats["duplicates_removed"], stats["chunks_dropped_for_budget"],
        stats["chars_in"], stats["chars_out"], stats["compression_ratio"],
        stats["cross_encoder_applied"],
    )

    return ContextFusionResult(results=compression_result.results, prompt=built, stats=stats)
