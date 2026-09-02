"""
Complexity Analyzer  –  Phase 7 Module 5 (Step: Complexity Analyzer)
------------------------------------------------------------------------
Scores a query's retrieval complexity as simple | medium | complex.

The score is a weighted sum of independently interpretable signals so the
classification is explainable (each factor is returned alongside the
final label) rather than an opaque model call:

  - length          : longer questions tend to need more context
  - sub_questions   : multiple asks joined by "and"/";"/"?" require
                       retrieving evidence for each part
  - entities        : more named entities ⇒ more grounding facts needed
  - comparison      : comparing things needs evidence from >1 source/version
  - temporal_range   : a date RANGE (not a single point in time) needs
                       evidence spanning multiple document versions

Thresholds are configurable via settings.complexity_medium_threshold /
complexity_complex_threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict

from app.core.config import settings

_CONJUNCTION_RE = re.compile(r"\b(and|or|but|as well as|along with)\b", re.IGNORECASE)


@dataclass
class ComplexityResult:
    level: str                     # "simple" | "medium" | "complex"
    score: float
    factors: Dict[str, float] = field(default_factory=dict)


def analyze_complexity(
    word_count: int,
    sub_question_count: int,
    entity_count: int,
    intent: str,
    has_temporal_range: bool = False,
    normalized_query: str = "",
) -> ComplexityResult:
    """
    Compute a complexity score and bucket it into simple/medium/complex.

    Args:
        word_count:          Words in the normalised query.
        sub_question_count:  Number of sub-questions detected by the parser.
        entity_count:        Named entities extracted by the NER step.
        intent:               Detected intent (comparison queries score higher).
        has_temporal_range:  True if the query spans a date range (Step: Temporal).
        normalized_query:    Used to count coordinating conjunctions.

    Returns:
        ComplexityResult with the bucketed level, raw score, and a factor
        breakdown for explainability.
    """
    factors: Dict[str, float] = {}

    # Length: 0 up to ~5 words, then +1 per 6 extra words (capped)
    factors["length"] = min(max(word_count - 5, 0) / 6.0, 3.0)

    # Sub-questions: first one is free, each extra adds weight
    factors["sub_questions"] = max(sub_question_count - 1, 0) * 1.5

    # Entities: first two are free, extras add weight
    factors["entities"] = max(entity_count - 2, 0) * 0.75

    # Comparison intent inherently needs multi-source evidence
    factors["comparison_intent"] = 2.0 if intent == "comparison" else 0.0

    # A date RANGE (e.g. "between 2022 and 2025") needs cross-version evidence
    factors["temporal_range"] = 2.0 if has_temporal_range else 0.0

    # Coordinating conjunctions ("and", "or", ...) signal compound asks
    conj_count = len(_CONJUNCTION_RE.findall(normalized_query))
    factors["conjunctions"] = min(conj_count * 0.5, 2.0)

    score = round(sum(factors.values()), 2)

    if score >= settings.complexity_complex_threshold:
        level = "complex"
    elif score >= settings.complexity_medium_threshold:
        level = "medium"
    else:
        level = "simple"

    return ComplexityResult(level=level, score=score, factors=factors)
