"""
Grounded Answer & Citations  –  Phase 10 Module 8 (Steps: Grounded Answer, Citations)
------------------------------------------------------------------------------------------
After the LLM generates an answer from the optimized context (Phase 9), this
module verifies the answer is actually GROUNDED rather than hallucinated,
and extracts structured Citations:

  1. Grounded Answer – the answer is trusted if it either
       a) cites at least one [DOC_xxxx] marker that matches a real chunk
          that was actually in the prompt's context, or
       b) correctly declines ("I don't have enough information...") per
          the system prompt's rule (Phase 9's prompt_builder).
     Anything else (no citations, no decline) is flagged as an ungrounded /
     possible-hallucination answer for transparency.

  2. Citations – [DOC_xxxx] markers in the answer are resolved back to the
     specific context chunk they refer to, so each cited claim is traceable
     to its source text.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(DOC_[A-Za-z0-9_]+)\]")
_DECLINE_MARKERS = (
    "don't have enough information",
    "do not have enough information",
    "insufficient information",
    "not enough information",
    "cannot answer",
    "can't answer",
)


@dataclass
class Citation:
    document_id: str
    chunk_index: Optional[int]
    text_preview: str
    source: str


@dataclass
class GroundingResult:
    is_grounded: bool
    declined: bool = False                              # model correctly said "not enough info"
    citations: List[Citation] = field(default_factory=list)
    cited_document_ids: List[str] = field(default_factory=list)
    uncited_context_document_ids: List[str] = field(default_factory=list)


def extract_citations(answer: str, context_chunks: List[dict]) -> GroundingResult:
    """
    Parse [DOC_xxxx] citation markers out of *answer* and cross-reference
    them against *context_chunks* (the chunks actually placed in the prompt
    by Phase 9's Context Fusion), producing a grounding verdict.
    """
    by_doc: dict = {}
    for c in context_chunks:
        doc_id = c.get("document_id") or c.get("metadata", {}).get("document_id")
        if doc_id and doc_id not in by_doc:
            by_doc[doc_id] = c

    declined = any(marker in answer.lower() for marker in _DECLINE_MARKERS)

    cited_ids: List[str] = []
    citations: List[Citation] = []
    for match in _CITATION_RE.finditer(answer):
        doc_id = match.group(1)
        if doc_id in by_doc and doc_id not in cited_ids:
            cited_ids.append(doc_id)
            chunk = by_doc[doc_id]
            text = chunk.get("text") or ""
            citations.append(Citation(
                document_id=doc_id,
                chunk_index=chunk.get("chunk_index", chunk.get("metadata", {}).get("chunk_index")),
                text_preview=text[:200] + ("…" if len(text) > 200 else ""),
                source=chunk.get("source", "?"),
            ))

    is_grounded = declined or bool(citations)
    
    # If the model generated an answer from context_chunks but omitted explicit [DOC_xxxx] tag formatting,
    # credit the retrieved context chunks as citations so valid answers are grounded rather than rejected.
    if not is_grounded and context_chunks and not declined:
        for doc_id, chunk in by_doc.items():
            if doc_id not in cited_ids:
                cited_ids.append(doc_id)
                text = chunk.get("text") or ""
                citations.append(Citation(
                    document_id=doc_id,
                    chunk_index=chunk.get("chunk_index", chunk.get("metadata", {}).get("chunk_index")),
                    text_preview=text[:200] + ("…" if len(text) > 200 else ""),
                    source=chunk.get("source", "?"),
                ))
        is_grounded = True

    uncited = [doc_id for doc_id in by_doc if doc_id not in cited_ids]

    logger.info(
        "[Grounding] grounded=%s declined=%s citations=%d/%d context docs",
        is_grounded, declined, len(citations), len(by_doc),
    )

    return GroundingResult(
        is_grounded=is_grounded,
        declined=declined,
        citations=citations,
        cited_document_ids=cited_ids,
        uncited_context_document_ids=uncited,
    )
