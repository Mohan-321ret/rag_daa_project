"""
Fact Verification, Confidence Score & Hallucination Detection
Phase 11 Module 9 (Steps 3-5)
------------------------------------------------------------------------------------------
For each extracted claim, finds the best-matching evidence sentence and
classifies the claim as:

  supported     – evidence found, numeric values MATCH
  contradicted  – evidence found for the same underlying fact, values DIFFER
                  (the concrete hallucination case: "30 days" vs "25 days")
  unverifiable  – no semantically-matching evidence sentence found at all,
                  or the claim had nothing mechanically checkable in it

Evidence sentences are matched to the claim by SEMANTIC (embedding cosine)
similarity, not lexical/text similarity: an LLM paraphrases far more
freely than a document revision does, so a claim like "Leave policy is 30
days" and its evidence "Employees receive 25 annual leave days per
calendar year" share almost no vocabulary (lexical match ≈ 0.39) but are
obviously about the same fact (embedding cosine ≈ 0.69). Both the claim
and evidence sentences have their numbers masked before embedding, so the
match is driven by what the sentence is ABOUT, not which number it states
— the numbers are compared separately, after the match is made.

A confidence score is then aggregated: contradictions penalise heavily
(the answer contains an outright wrong fact), unverifiable claims
penalise lightly (unproven, not necessarily wrong), non-quantitative
claims don't affect the score (nothing to mechanically check).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.services.claim_extractor import Claim
from app.services.embedding_service import embed_batch, embed_text

logger = logging.getLogger(__name__)

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _mask_numbers(sentence: str) -> str:
    return _NUM_RE.sub("<NUM>", sentence).lower()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


@dataclass
class ClaimVerification:
    claim: Claim
    status: str                                  # supported | contradicted | unverifiable
    evidence_document_id: Optional[str] = None
    evidence_chunk_index: Optional[int] = None
    evidence_text: Optional[str] = None
    evidence_values: List[str] = field(default_factory=list)
    statement_similarity: float = 0.0


def _evidence_sentences(evidence_chunks: List[dict]) -> List[Tuple[str, Optional[str], Optional[int]]]:
    """Flatten evidence chunks into (sentence, document_id, chunk_index) tuples."""
    out = []
    for chunk in evidence_chunks:
        text = chunk.get("text") or ""
        doc_id = chunk.get("document_id") or chunk.get("metadata", {}).get("document_id")
        chunk_idx = chunk.get("chunk_index", chunk.get("metadata", {}).get("chunk_index"))
        for sent in _SENT_SPLIT_RE.split(text):
            sent = sent.strip()
            if len(sent) >= 8:
                out.append((sent, doc_id, chunk_idx))
    return out


def verify_claim(claim: Claim, evidence_chunks: List[dict]) -> ClaimVerification:
    """
    Compare *claim* against *evidence_chunks* and classify it as
    supported / contradicted / unverifiable.
    """
    if not claim.is_quantitative:
        return ClaimVerification(claim=claim, status="unverifiable")

    candidates = _evidence_sentences(evidence_chunks)
    if not candidates:
        return ClaimVerification(claim=claim, status="unverifiable")

    threshold = settings.verification_statement_similarity_threshold

    claim_vec = np.array(embed_text(_mask_numbers(claim.clean_text)))
    candidate_texts = [_mask_numbers(sent) for sent, _, _ in candidates]
    candidate_vecs = np.array(embed_batch(candidate_texts))

    best_idx = -1
    best_sim = 0.0
    for i, vec in enumerate(candidate_vecs):
        sim = _cosine(claim_vec, vec)
        if sim > best_sim:
            best_sim = sim
            best_idx = i

    if best_idx == -1 or best_sim < threshold:
        return ClaimVerification(
            claim=claim, status="unverifiable", statement_similarity=round(best_sim, 4)
        )

    sent, doc_id, chunk_idx = candidates[best_idx]
    clean_sent = re.sub(r"\bDOC_[A-Za-z0-9_]+\b|\bchunk\s*\d+\b", "", sent, flags=re.IGNORECASE)
    evidence_values = _NUM_RE.findall(clean_sent)

    def _norm(v: str) -> str:
        c = v.rstrip("%").replace(",", "").lstrip("0")
        return c if c else "0"

    norm_claim = {_norm(v) for v in claim.values}
    norm_ev = {_norm(v) for v in evidence_values}
    
    # Supported if normalized claim numbers are subset of evidence or vice versa, or if evidence values match
    status = "supported" if (norm_claim.issubset(norm_ev) or norm_ev.issubset(norm_claim)) else "contradicted"

    verification = ClaimVerification(
        claim=claim,
        status=status,
        evidence_document_id=doc_id,
        evidence_chunk_index=chunk_idx,
        evidence_text=sent,
        evidence_values=evidence_values,
        statement_similarity=round(best_sim, 4),
    )

    if status == "contradicted":
        logger.warning(
            "[FactVerifier] ⚠️ Contradiction | claim=%r values=%s | evidence=%r values=%s (%s)",
            claim.clean_text, claim.values, sent, evidence_values, doc_id,
        )
    return verification


def compute_confidence(verifications: List[ClaimVerification]) -> float:
    """
    Aggregate a 0..1 confidence score. Non-quantitative claims (nothing
    mechanically checkable) don't move the score; among checkable claims,
    contradictions cost far more than unverifiable ones.
    """
    checkable = [v for v in verifications if v.claim.is_quantitative]
    if not checkable:
        return 1.0  # nothing mechanically checkable -> no detected reason to distrust it

    score = 1.0
    for v in checkable:
        if v.status == "contradicted":
            score -= 1.0 / len(checkable)
        elif v.status == "unverifiable":
            score -= 0.4 / len(checkable)
    return round(max(0.0, min(1.0, score)), 4)


def detect_hallucinations(verifications: List[ClaimVerification]) -> List[ClaimVerification]:
    """Contradicted claims are definite hallucinations; list them before unverifiable ones."""
    contradicted = [v for v in verifications if v.status == "contradicted"]
    unverifiable = [
        v for v in verifications if v.status == "unverifiable" and v.claim.is_quantitative
    ]
    return contradicted + unverifiable
