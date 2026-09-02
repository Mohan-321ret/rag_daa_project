"""
Conflict Detector  –  Phase 6 Module 3 (Step 4)
-------------------------------------------------
Flags CONTRADICTING FACTS between two document versions.

Example:
    Old policy:  "Employees are entitled to 20 days of annual leave."
    New policy:  "Employees are entitled to 25 days of annual leave."
    →  CONFLICT: same statement, different value (20 → 25).

Method (deterministic, no LLM required):
  1. Extract fact-bearing sentences (those containing numbers/percentages)
     from both versions.
  2. Normalise each sentence by masking numbers with <NUM> so that two
     versions of the *same rule* become lexically comparable.
  3. Pair old↔new sentences whose normalised forms are highly similar
     (difflib ratio ≥ conflict_fuzzy_threshold).
  4. If a paired sentence's numeric values differ → flag a conflict with
     the old value(s), new value(s), and both statements.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)

# Matches integers, decimals (both . and , separators) and percentages
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
# Sentence boundary: punctuation followed by whitespace, or a newline
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


@dataclass
class Conflict:
    """One detected contradiction between the old and new version."""
    old_statement: str
    new_statement: str
    old_values: List[str]
    new_values: List[str]
    statement_similarity: float   # similarity of the masked statements (0..1)


@dataclass
class ConflictResult:
    conflicts: List[Conflict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.conflicts)

    def to_dicts(self) -> List[dict]:
        return [
            {
                "old_statement": c.old_statement,
                "new_statement": c.new_statement,
                "old_values": c.old_values,
                "new_values": c.new_values,
                "statement_similarity": c.statement_similarity,
            }
            for c in self.conflicts
        ]


def _fact_sentences(text: str, limit: int = 300) -> List[str]:
    """Extract number-bearing sentences (likely factual statements)."""
    sentences = []
    for raw in _SENT_SPLIT_RE.split(text or ""):
        s = " ".join(raw.split())  # collapse whitespace
        if 15 <= len(s) <= 500 and _NUM_RE.search(s):
            sentences.append(s)
        if len(sentences) >= limit:
            break
    return sentences


def _mask_numbers(sentence: str) -> str:
    """Replace all numeric values with <NUM> to compare statement structure."""
    return _NUM_RE.sub("<NUM>", sentence).lower()


def detect_conflicts(old_text: str, new_text: str) -> ConflictResult:
    """
    Find factual contradictions between two document versions.

    Returns:
        ConflictResult with up to `settings.max_conflicts_reported` conflicts,
        ordered by statement similarity (most confident first).
    """
    old_sents = _fact_sentences(old_text)
    new_sents = _fact_sentences(new_text)

    if not old_sents or not new_sents:
        logger.info("[ConflictDetector] No fact-bearing sentences to compare.")
        return ConflictResult()

    new_masked = [_mask_numbers(s) for s in new_sents]
    threshold = settings.conflict_fuzzy_threshold

    conflicts: List[Conflict] = []
    used_new: set[int] = set()

    for old_s in old_sents:
        old_masked = _mask_numbers(old_s)
        old_values = _NUM_RE.findall(old_s)

        # Find the best-matching new statement for this old statement
        best_idx, best_ratio = -1, 0.0
        for j, cand_masked in enumerate(new_masked):
            if j in used_new:
                continue
            ratio = difflib.SequenceMatcher(None, old_masked, cand_masked).ratio()
            if ratio > best_ratio:
                best_idx, best_ratio = j, ratio

        if best_idx == -1 or best_ratio < threshold:
            continue  # statement disappeared or changed beyond recognition

        new_values = _NUM_RE.findall(new_sents[best_idx])
        if old_values != new_values:
            used_new.add(best_idx)
            conflicts.append(Conflict(
                old_statement=old_s,
                new_statement=new_sents[best_idx],
                old_values=old_values,
                new_values=new_values,
                statement_similarity=round(best_ratio, 4),
            ))

    conflicts.sort(key=lambda c: c.statement_similarity, reverse=True)
    conflicts = conflicts[: settings.max_conflicts_reported]

    logger.info(
        "[ConflictDetector] %d conflict(s) flagged between versions.",
        len(conflicts),
    )
    return ConflictResult(conflicts=conflicts)
