"""
Text Cleaner Service  –  Phase 3 Module 2 (Steps 1 & 2)
---------------------------------------------------------
Step 1 – Text Cleaning:
  • Strip residual HTML / XML tags
  • Detect and remove repeated running headers / footers
  • Collapse excess whitespace

Step 2 – Noise Removal:
  • Erase page-number patterns  (Page N of M, - N -, standalone digit lines …)
  • Remove repeated disclaimer / boiler-plate paragraphs
  • Remove common watermark text patterns
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import List

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    """
    Run the full text-cleaning pipeline (Steps 1 & 2).

    Pipeline order:
      1. Strip HTML / XML tags
      2. Remove page-number patterns
      3. Remove watermark patterns
      4. Remove repeated running headers/footers
      5. Remove repeated disclaimer blocks
      6. Final whitespace normalisation

    Args:
        raw: Raw extracted text (may contain HTML tags, noise, etc.)

    Returns:
        Cleaned text string.
    """
    if not raw or not raw.strip():
        return ""

    text = raw

    # Step 1a – strip HTML / XML tags
    text = _strip_html(text)

    # Step 2a – remove page-number lines
    text = _remove_page_numbers(text)

    # Step 2b – remove watermark patterns
    text = _remove_watermarks(text)

    # Step 1b – remove repeated running headers / footers (structural noise)
    text = _remove_repeated_lines(text)

    # Step 2c – remove repeated boiler-plate / disclaimer blocks
    text = _remove_duplicate_paragraphs(text)

    # Final whitespace cleanup
    text = _normalise_whitespace(text)

    logger.debug(
        "[TextCleaner] Cleaned text | in=%d chars -> out=%d chars",
        len(raw), len(text),
    )
    return text


# ── Step 1a – HTML stripping ──────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """
    Remove HTML / XML markup using BeautifulSoup, then unescape entities.
    Falls back gracefully if the input is plain text.
    """
    try:
        soup = BeautifulSoup(text, "lxml")
        # Remove script and style elements entirely
        for tag in soup(["script", "style", "head", "meta", "link"]):
            tag.decompose()
        cleaned = soup.get_text(separator="\n")
    except Exception:
        # If parsing fails, fall back to a regex strip
        cleaned = re.sub(r"<[^>]+>", " ", text)

    # Unescape common HTML entities
    replacements = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
        "&hellip;": "...", "&mdash;": "-", "&ndash;": "-",
    }
    for entity, char in replacements.items():
        cleaned = cleaned.replace(entity, char)

    return cleaned


# ── Step 2a – Page-number removal ────────────────────────────────────────────

# Patterns that indicate a line is purely a page number or page label
_PAGE_NUMBER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*-\s*\d+\s*-\s*$"),                    # - 3 -
    re.compile(r"^\s*\d+\s*$"),                              # standalone digit
    re.compile(r"^\s*page\s+\d+\s*(of\s+\d+)?\s*$", re.I), # Page 3 / Page 3 of 10
    re.compile(r"^\s*p\.\s*\d+\s*$", re.I),                 # p. 12
    re.compile(r"^\s*\[\s*\d+\s*\]\s*$"),                   # [4]
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),                   # 4/20
]


def _remove_page_numbers(text: str) -> str:
    """Remove lines that match common page-number patterns."""
    lines = text.split("\n")
    cleaned_lines = [
        line for line in lines
        if not any(pat.match(line) for pat in _PAGE_NUMBER_PATTERNS)
    ]
    return "\n".join(cleaned_lines)


# ── Step 2b – Watermark removal ───────────────────────────────────────────────

_WATERMARK_PATTERNS: list[re.Pattern] = [
    re.compile(r"^CONFIDENTIAL$", re.I),
    re.compile(r"^DRAFT$", re.I),
    re.compile(r"^DO NOT DISTRIBUTE$", re.I),
    re.compile(r"^INTERNAL USE ONLY$", re.I),
    re.compile(r"^PROPRIETARY$", re.I),
    re.compile(r"^CLASSIFIED$", re.I),
    re.compile(r"^WATERMARK$", re.I),
    re.compile(r"^SAMPLE DOCUMENT$", re.I),
    re.compile(r"^FOR REVIEW ONLY$", re.I),
]


def _remove_watermarks(text: str) -> str:
    """
    Remove lines that consist *only* of a watermark keyword.
    Lines with real content that happen to contain these words are kept.
    Only short lines (< 80 chars) are checked to avoid false positives.
    """
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_watermark = (
            len(stripped) < 80
            and any(pat.fullmatch(stripped) for pat in _WATERMARK_PATTERNS)
        )
        if not is_watermark:
            cleaned.append(line)
    return "\n".join(cleaned)


# ── Step 1b – Repeated running headers / footers ──────────────────────────────

def _remove_repeated_lines(text: str, min_repeat: int = 3) -> str:
    """
    Detect lines that appear >= *min_repeat* times throughout the document
    and remove them – these are characteristic of running headers/footers
    stamped on every page.

    Only short lines (<= 120 chars) are considered candidates.
    """
    lines = text.split("\n")
    stripped_lines = [line.strip() for line in lines]

    # Count occurrences of each non-empty short line
    counter = Counter(
        line for line in stripped_lines if line and len(line) <= 120
    )

    # Build set of lines that repeat enough to be headers/footers
    repeated = {line for line, count in counter.items() if count >= min_repeat}

    if not repeated:
        return text

    logger.debug(
        "[TextCleaner] Detected %d repeated header/footer line(s): %s",
        len(repeated), list(repeated)[:5],
    )

    cleaned_lines = [
        line for line in lines if line.strip() not in repeated
    ]
    return "\n".join(cleaned_lines)


# ── Step 2c – Duplicate paragraph / disclaimer removal ───────────────────────

def _remove_duplicate_paragraphs(text: str) -> str:
    """
    Split text into paragraphs (double-newline separated) and deduplicate.
    Paragraphs are compared after stripping/normalising whitespace.
    Order is preserved; first occurrence is kept.
    """
    paragraphs = re.split(r"\n{2,}", text)
    seen: set[str] = set()
    unique: list[str] = []

    for para in paragraphs:
        key = re.sub(r"\s+", " ", para).strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(para)

    return "\n\n".join(unique)


# ── Final whitespace normalisation ────────────────────────────────────────────

def _normalise_whitespace(text: str) -> str:
    """
    - Normalise line endings
    - Collapse horizontal whitespace within lines
    - Collapse runs of >2 blank lines to exactly 2
    - Strip overall leading/trailing whitespace
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]

    result: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 2:
                result.append("")
        else:
            blank_run = 0
            result.append(line)

    return "\n".join(result).strip()
