"""
Context Compression  –  Phase 9 Module 7 (Step 3: Context Compression)
------------------------------------------------------------------------
Even after dedup + cross-encoder ranking, chunks can be verbose relative to
what the LLM actually needs. This step:

  1. Extractively trims each chunk to its most query-relevant sentences
     (lexical overlap scoring — cheap, no extra model call), keeping the
     surviving sentences in their ORIGINAL order for readability, and
     never dropping below a minimum sentence count.
  2. Enforces a total context character budget across all chunks, adding
     chunks in relevance order (they arrive pre-sorted by the cross-encoder
     step) until the budget is spent, so the prompt never blows past the
     LLM's usable context window.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\w+")


@dataclass
class CompressionResult:
    results: List[dict] = field(default_factory=list)
    chunks_in: int = 0
    chunks_out: int = 0
    chars_in: int = 0
    chars_out: int = 0
    dropped_for_budget: int = 0

    @property
    def compression_ratio(self) -> float:
        return round(self.chars_out / self.chars_in, 4) if self.chars_in else 1.0


def _split_sentences(text: str) -> List[str]:
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]
    return sentences or ([text.strip()] if (text or "").strip() else [])


def _sentence_relevance(sentence: str, query_tokens: set) -> float:
    tokens = set(_WORD_RE.findall(sentence.lower()))
    if not tokens:
        return 0.0
    return len(tokens & query_tokens) / len(tokens)


def _compress_chunk_text(
    text: str, query_tokens: set, max_chars: int, min_sentences: int
) -> Tuple[str, int, int]:
    """Trim one chunk to its most relevant sentences, in original order."""
    original_len = len(text or "")
    if original_len <= max_chars:
        return text, original_len, original_len

    sentences = _split_sentences(text)
    if len(sentences) <= min_sentences:
        return text[:max_chars], original_len, min(original_len, max_chars)

    ranked_indices = sorted(
        range(len(sentences)),
        key=lambda i: _sentence_relevance(sentences[i], query_tokens),
        reverse=True,
    )

    keep: set = set()
    running_len = 0
    for idx in ranked_indices:
        s_len = len(sentences[idx]) + 1
        if running_len + s_len > max_chars and len(keep) >= min_sentences:
            continue
        keep.add(idx)
        running_len += s_len

    if not keep:
        keep = set(range(min(min_sentences, len(sentences))))

    compressed = " ".join(sentences[i] for i in sorted(keep))
    return compressed, original_len, len(compressed)


def compress_context(
    query: str,
    results: List[dict],
    max_total_chars: Optional[int] = None,
    max_chunk_chars: Optional[int] = None,
    min_sentences: Optional[int] = None,
) -> CompressionResult:
    """
    Compress *results* (already deduped + reranked, best-first) to fit a
    total character budget, trimming each chunk to its most relevant
    sentences along the way.
    """
    max_total_chars = max_total_chars if max_total_chars is not None else settings.context_max_chars
    max_chunk_chars = max_chunk_chars if max_chunk_chars is not None else settings.context_chunk_max_chars
    min_sentences = min_sentences if min_sentences is not None else settings.context_min_sentences_per_chunk

    if not results:
        return CompressionResult()

    query_tokens = set(_WORD_RE.findall(query.lower()))

    compressed: List[dict] = []
    chars_in = 0
    chars_out = 0
    dropped = 0

    for r in results:
        text = r.get("text") or ""
        chars_in += len(text)

        comp_text, orig_len, comp_len = _compress_chunk_text(
            text, query_tokens, max_chunk_chars, min_sentences
        )

        if compressed and chars_out + comp_len > max_total_chars:
            dropped += 1
            continue

        item = dict(r)
        item["text"] = comp_text
        item["original_char_count"] = orig_len
        item["compressed_char_count"] = comp_len
        compressed.append(item)
        chars_out += comp_len

    # Safety net: a single chunk alone can exceed the total budget (it's
    # always kept — never zero results — but must not blow the budget).
    if compressed and chars_out > max_total_chars:
        overflow = chars_out - max_total_chars
        last = compressed[-1]
        trimmed_len = max(0, len(last["text"]) - overflow)
        last["text"] = last["text"][:trimmed_len]
        last["compressed_char_count"] = trimmed_len
        chars_out = max_total_chars

    result = CompressionResult(
        results=compressed,
        chunks_in=len(results),
        chunks_out=len(compressed),
        chars_in=chars_in,
        chars_out=chars_out,
        dropped_for_budget=dropped,
    )
    logger.info(
        "[ContextCompression] %d->%d chunks | %d->%d chars (ratio=%.2f) | dropped=%d",
        result.chunks_in, result.chunks_out, result.chars_in, result.chars_out,
        result.compression_ratio, result.dropped_for_budget,
    )
    return result
