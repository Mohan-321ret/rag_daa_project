"""
Answer Rewriter  –  Phase 11 Module 9 (Step 6: Rewrite Answer)
------------------------------------------------------------------
When Fact Verification finds a CONTRADICTED claim (the LLM's stated value
disagrees with independently retrieved evidence), this step deterministically
corrects the offending sentence using the evidence itself, attributed to
its source:

    LLM:      "Leave policy is 30 days."
    Evidence: "Employees receive 25 annual leave days." (DOC_HR5)
    Rewrite:  "According to DOC_HR5, employees receive 25 annual leave days."

Correction SUBSTITUTES the evidence sentence for the contradicted one
(with a source-attribution prefix) rather than patching the number in
place — safer, since the corrected text is guaranteed to be something
actually retrieved from the knowledge base rather than a syntactic
patch-job that could still be wrong in other ways. Non-contradicted
sentences are left exactly as the LLM wrote them. No LLM call is made
here deliberately: an LLM "fixing" a hallucination risks introducing a
new one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from app.services.fact_verifier import ClaimVerification

logger = logging.getLogger(__name__)


@dataclass
class Correction:
    original: str
    corrected: str
    evidence_document_id: str


@dataclass
class RewriteResult:
    answer: str
    was_rewritten: bool
    corrections: List[Correction] = field(default_factory=list)


def _attribute(sentence: str, document_id: str) -> str:
    """Prefix an evidence sentence with a source attribution, lower-casing
    its first letter so it reads naturally after "According to X, ..."."""
    if not sentence:
        return sentence
    lowered = sentence[0].lower() + sentence[1:] if sentence[0].isupper() else sentence
    return f"According to {document_id}, {lowered}"


def rewrite_answer(original_answer: str, verifications: List[ClaimVerification]) -> RewriteResult:
    """Replace any contradicted sentence with an evidence-grounded restatement."""
    contradicted = [
        v for v in verifications
        if v.status == "contradicted" and v.evidence_text and v.evidence_document_id
    ]
    if not contradicted:
        return RewriteResult(answer=original_answer, was_rewritten=False)

    rewritten = original_answer
    corrections: List[Correction] = []
    for v in contradicted:
        replacement = _attribute(v.evidence_text, v.evidence_document_id)
        original_sentence = v.claim.text
        if original_sentence in rewritten:
            rewritten = rewritten.replace(original_sentence, replacement)
        else:
            # Sentence text shifted during upstream processing – append the
            # correction rather than silently dropping it.
            rewritten = f"{rewritten} {replacement}"
        corrections.append(Correction(
            original=original_sentence,
            corrected=replacement,
            evidence_document_id=v.evidence_document_id,
        ))

    logger.info("[AnswerRewriter] ✏️ Corrected %d hallucinated claim(s).", len(corrections))
    return RewriteResult(answer=rewritten, was_rewritten=True, corrections=corrections)
