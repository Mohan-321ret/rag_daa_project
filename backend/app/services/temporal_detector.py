"""
Temporal Detection  –  Phase 7 Module 5 (Step: Temporal Detection)
------------------------------------------------------------------------
Detects temporal signals in a query: relative time words ("today", "old",
"previous", "before", "recently") and explicit years ("2023"), then
classifies the overall temporal scope:

  none              – no temporal signal ("What is the leave policy?")
  current           – asking about the present/latest state
  historical        – asking about a past state ("the old policy")
  point_in_time     – asking about one specific year/date
  range_comparison  – asking about a span between two points
                       ("between 2022 and 2025", "from 2020 to now")

This scope feeds both the Complexity Analyzer (a range needs cross-version
evidence) and, downstream, can route "range_comparison" + "comparison"
intent queries into the Module 3 (Phase 6) version-history/diff endpoints.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

_RANGE_PHRASE_RE = re.compile(
    r"\bbetween\b.+\band\b|\bfrom\b.+\b(?:to|until|through)\b", re.IGNORECASE
)

_CURRENT_WORDS_RE = re.compile(
    r"\b(today|now|currently|current|latest|present|up[- ]to[- ]date)\b",
    re.IGNORECASE,
)
_HISTORICAL_WORDS_RE = re.compile(
    r"\b(old|older|previous|previously|before|prior|earlier|past|formerly|"
    r"used to|historical|history|back then|originally)\b",
    re.IGNORECASE,
)


@dataclass
class TemporalResult:
    has_temporal: bool
    scope: str                        # none | current | historical | point_in_time | range_comparison
    expressions: List[str] = field(default_factory=list)  # matched keyword phrases
    years: List[int] = field(default_factory=list)        # distinct years mentioned, sorted


def detect_temporal(normalized_query: str) -> TemporalResult:
    """
    Detect temporal keywords and explicit years, then classify the query's
    temporal scope.
    """
    q = normalized_query
    years = sorted({int(y) for y in _YEAR_RE.findall(q)})

    expressions: List[str] = []
    current_hit = bool(_CURRENT_WORDS_RE.search(q))
    historical_hit = bool(_HISTORICAL_WORDS_RE.search(q))
    range_phrase_hit = bool(_RANGE_PHRASE_RE.search(q))

    if current_hit:
        expressions.extend(m.group(0) for m in _CURRENT_WORDS_RE.finditer(q))
    if historical_hit:
        expressions.extend(m.group(0) for m in _HISTORICAL_WORDS_RE.finditer(q))
    if years:
        expressions.extend(str(y) for y in years)

    has_temporal = bool(current_hit or historical_hit or years)

    # ── Scope classification (priority: range > historical > current > point) ─
    if len(years) >= 2 or (range_phrase_hit and (years or historical_hit or current_hit)):
        scope = "range_comparison"
    elif historical_hit or (len(years) == 1 and _is_past_year(years[0])):
        scope = "historical"
    elif current_hit or not years:
        scope = "current" if has_temporal else "none"
    else:
        scope = "point_in_time"

    return TemporalResult(
        has_temporal=has_temporal,
        scope=scope,
        expressions=sorted(set(expressions)),
        years=years,
    )


def _is_past_year(year: int) -> bool:
    """A lone year more than one year behind today is treated as historical."""
    return year < datetime.now(timezone.utc).year - 1
