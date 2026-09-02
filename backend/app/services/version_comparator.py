"""
Version Comparator  –  Phase 6 Module 3 (Step 2)
--------------------------------------------------
Compares an OLD document version against a NEW document version and
generates a structured diff:

  Old Document ──┐
                 ├─→  unified diff + line-level change statistics
  New Document ──┘

Uses Python's difflib (SequenceMatcher + unified_diff) so no external
dependency is required.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VersionDiff:
    """Structured result of comparing two document versions."""
    lines_added: int = 0
    lines_removed: int = 0
    lines_modified: int = 0
    text_similarity: float = 1.0          # difflib ratio 0..1 (1 = identical)
    unified_diff: str = ""                # human-readable diff (capped)
    added_lines: List[str] = field(default_factory=list)     # sample of new lines
    removed_lines: List[str] = field(default_factory=list)   # sample of dropped lines

    @property
    def has_changes(self) -> bool:
        return bool(self.lines_added or self.lines_removed or self.lines_modified)


def _significant_lines(text: str) -> List[str]:
    """Split text into non-empty, stripped lines for stable diffing."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def compare_versions(
    old_text: str,
    new_text: str,
    old_label: str = "old",
    new_label: str = "new",
) -> VersionDiff:
    """
    Generate a diff between two document texts.

    Args:
        old_text:  Extracted text of the previous version.
        new_text:  Extracted text of the incoming version.
        old_label: Label shown in the unified diff header (e.g. DOC_1001 v1).
        new_label: Label shown in the unified diff header (e.g. DOC_1002 v2).

    Returns:
        VersionDiff with line statistics, similarity ratio, and unified diff.
    """
    old_lines = _significant_lines(old_text or "")
    new_lines = _significant_lines(new_text or "")

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)

    diff = VersionDiff()
    diff.text_similarity = round(matcher.ratio(), 4)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            diff.lines_added += j2 - j1
            diff.added_lines.extend(new_lines[j1:j2])
        elif tag == "delete":
            diff.lines_removed += i2 - i1
            diff.removed_lines.extend(old_lines[i1:i2])
        elif tag == "replace":
            diff.lines_modified += max(i2 - i1, j2 - j1)
            diff.removed_lines.extend(old_lines[i1:i2])
            diff.added_lines.extend(new_lines[j1:j2])

    # Keep only a readable sample of changed lines
    diff.added_lines = diff.added_lines[:25]
    diff.removed_lines = diff.removed_lines[:25]

    unified = "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_label,
            tofile=new_label,
            lineterm="",
            n=2,
        )
    )
    if len(unified) > settings.max_diff_chars:
        unified = unified[: settings.max_diff_chars] + "\n… [diff truncated]"
    diff.unified_diff = unified

    logger.info(
        "[VersionComparator] %s → %s | +%d −%d ~%d lines | similarity=%.4f",
        old_label, new_label,
        diff.lines_added, diff.lines_removed, diff.lines_modified,
        diff.text_similarity,
    )
    return diff
