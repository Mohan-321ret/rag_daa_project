"""
Query Parser  –  Phase 7 Module 5 (Step: Normalize)
------------------------------------------------------
Normalises a raw user question before it is fed into intent detection, NER,
complexity analysis, and temporal detection:

  1. Unicode NFC normalisation + smart-quote/whitespace cleanup
  2. Collapse repeated whitespace, strip leading/trailing junk
  3. Strip a trailing "?" run down to a single "?"
  4. Split into candidate sub-questions on hard separators ("?", " and ", ";")
     so the complexity analyzer can count them without re-parsing text.

This is intentionally lightweight (no LLM call) since every query passes
through it on the hot path.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List

_WS_RE = re.compile(r"\s+")
_MULTI_PUNCT_RE = re.compile(r"([?!.]){2,}")
# Split on '?' / ';' / ' and ' / ' vs ' / ' versus ' as coordinators of separate asks
_SUBQUESTION_SPLIT_RE = re.compile(
    r"\?+\s*|\s*;\s*|\s+\band\b\s+(?=(?:what|how|why|when|where|who|which|compare|is|are|does|do)\b)",
    re.IGNORECASE,
)


@dataclass
class ParsedQuery:
    """Result of normalising a raw user query."""
    raw: str
    normalized: str
    sub_questions: List[str] = field(default_factory=list)
    word_count: int = 0
    char_count: int = 0


def _normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw or "")
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace(" ", " ")
    text = _WS_RE.sub(" ", text).strip()
    text = _MULTI_PUNCT_RE.sub(r"\1", text)
    return text


def parse_query(raw_query: str) -> ParsedQuery:
    """
    Normalize a raw query and split it into candidate sub-questions.

    Args:
        raw_query: The user's original natural-language question.

    Returns:
        ParsedQuery with the cleaned text, word/char counts, and a list of
        sub-question fragments (non-empty, trimmed).
    """
    normalized = _normalize_text(raw_query)

    fragments = [
        f.strip(" ?.;")
        for f in _SUBQUESTION_SPLIT_RE.split(normalized)
        if f and f.strip(" ?.;")
    ]
    if not fragments:
        fragments = [normalized] if normalized else []

    return ParsedQuery(
        raw=raw_query,
        normalized=normalized,
        sub_questions=fragments,
        word_count=len(normalized.split()) if normalized else 0,
        char_count=len(normalized),
    )
