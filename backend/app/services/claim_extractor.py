"""
Claim Extraction  –  Phase 11 Module 9 (Step 1: Claim Extraction)
------------------------------------------------------------------------
Breaks a generated answer into discrete, sentence-level claims so each one
can be independently fact-checked.

Sentences carrying a number/date/percentage are QUANTITATIVE claims — the
kind this module can mechanically verify against evidence (matching the
worked example: "Leave policy is 30 days"). Sentences without a number are
still extracted (so the full answer can be reassembled unchanged) but are
marked non-quantitative — verification treats those as unverifiable rather
than guessing at a mechanical check that doesn't apply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
_CITATION_RE = re.compile(r"\[(DOC_[A-Za-z0-9_]+)\]")
_CHUNK_REF_RE = re.compile(r"\bchunk\s*\d+\b", re.IGNORECASE)
_DOC_ID_REF_RE = re.compile(r"\bDOC_[A-Za-z0-9_]+\b", re.IGNORECASE)


@dataclass
class Claim:
    """One sentence-level, independently-checkable claim from an answer."""
    text: str                          # original sentence, including any [DOC_xxxx] marker
    clean_text: str                    # same sentence with citation markers stripped
    values: List[str] = field(default_factory=list)   # numbers found in the claim
    is_quantitative: bool = False
    cited_document_id: Optional[str] = None


def extract_claims(answer: str, min_chars: Optional[int] = None) -> List[Claim]:
    """Split *answer* into sentence-level claims for downstream verification."""
    min_chars = min_chars if min_chars is not None else settings.verification_min_claim_chars

    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(answer or "") if s.strip()]

    claims: List[Claim] = []
    for s in sentences:
        if len(s) < min_chars:
            continue
        cite_match = _CITATION_RE.search(s)
        clean = _CITATION_RE.sub("", s).strip()
        # Clean doc IDs and chunk numbers before extracting factual numbers
        clean_for_nums = _CHUNK_REF_RE.sub("", clean)
        clean_for_nums = _DOC_ID_REF_RE.sub("", clean_for_nums)
        values = _NUM_RE.findall(clean_for_nums)

        claims.append(Claim(
            text=s,
            clean_text=clean,
            values=values,
            is_quantitative=bool(values),
            cited_document_id=cite_match.group(1) if cite_match else None,
        ))
    return claims
