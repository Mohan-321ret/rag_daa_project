"""
Evidence Verification Engine  –  Phase 11 Module 9 (Orchestrator)
------------------------------------------------------------------------
Second major research contribution: independently fact-checks a generated
answer AFTER the LLM has spoken, instead of trusting its citations at
face value.

  Generated Answer
       ↓
  Step 1  Claim Extraction         [claim_extractor]
       ↓
  Step 2  Retrieve Evidence Again  [evidence_retriever]  – fresh retrieval per
       ↓                                                    claim, independent of
       ↓                                                    Phase 9's compressed prompt
  Step 3  Fact Verification        [fact_verifier]
       ↓
  Step 4  Confidence Score         [fact_verifier]
       ↓
  Step 5  Hallucination Detection  [fact_verifier]
       ↓
  Step 6  Rewrite Answer           [answer_rewriter]
       ↓
  Verified / corrected answer

Entry point: verify_answer(db, answer_text, document_id) -> VerificationResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.services.answer_rewriter import Correction, RewriteResult, rewrite_answer
from app.services.chunk_access_service import ChunkAccessContext
from app.services.claim_extractor import Claim, extract_claims
from app.services.evidence_retriever import retrieve_evidence
from app.services.fact_verifier import (
    ClaimVerification,
    compute_confidence,
    detect_hallucinations,
    verify_claim,
)

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    original_answer: str
    final_answer: str
    was_rewritten: bool
    confidence_score: float
    claims_total: int
    claims_checked: int             # quantitative (mechanically checkable) claims
    verifications: List[ClaimVerification] = field(default_factory=list)
    hallucinations: List[ClaimVerification] = field(default_factory=list)
    corrections: List[Correction] = field(default_factory=list)


def verify_answer(
    db: Session, answer_text: str, access_ctx: ChunkAccessContext, document_id: Optional[str] = None
) -> VerificationResult:
    """
    Run the full Evidence Verification pipeline over a generated answer.

    Args:
        access_ctx: Required — threaded to evidence_retriever.retrieve_evidence
                    (Domain-Aware Chunk Access Control: this step re-retrieves
                    independently of the main answer's context, so it needs
                    its own authorization pass — see that module's docstring).
        document_id: If the original question was scoped to one document,
                    pass it through so re-retrieved evidence (and any
                    correction) stays scoped to that same document instead
                    of searching the whole knowledge base.
    """
    # ─── Step 1: Claim Extraction ──────────────────────────────────────────────
    claims: List[Claim] = extract_claims(answer_text)

    # ─── Steps 2-3: Retrieve Evidence Again + Fact Verification (per claim) ───
    verifications: List[ClaimVerification] = []
    for claim in claims:
        evidence = (
            retrieve_evidence(db, claim.clean_text, access_ctx, document_id=document_id)
            if claim.is_quantitative else []
        )
        verifications.append(verify_claim(claim, evidence))

    # ─── Step 4: Confidence Score ──────────────────────────────────────────────
    confidence = compute_confidence(verifications)

    # ─── Step 5: Hallucination Detection ───────────────────────────────────────
    hallucinations = detect_hallucinations(verifications)

    # ─── Step 6: Rewrite Answer ─────────────────────────────────────────────────
    rewrite: RewriteResult = rewrite_answer(answer_text, verifications)

    logger.info(
        "[EvidenceVerification] ✅ claims=%d checkable=%d confidence=%.2f "
        "hallucinations=%d rewritten=%s",
        len(claims), sum(1 for c in claims if c.is_quantitative), confidence,
        len(hallucinations), rewrite.was_rewritten,
    )

    return VerificationResult(
        original_answer=answer_text,
        final_answer=rewrite.answer,
        was_rewritten=rewrite.was_rewritten,
        confidence_score=confidence,
        claims_total=len(claims),
        claims_checked=sum(1 for c in claims if c.is_quantitative),
        verifications=verifications,
        hallucinations=hallucinations,
        corrections=rewrite.corrections,
    )


def verification_result_to_dict(result: VerificationResult) -> dict:
    """Plain-dict projection of a VerificationResult, shared by the RAG
    response and the standalone /verification/verify endpoint."""
    return {
        "was_rewritten": result.was_rewritten,
        "confidence_score": result.confidence_score,
        "claims_total": result.claims_total,
        "claims_checked": result.claims_checked,
        "hallucinations_detected": len(result.hallucinations),
        "hallucinations": [
            {
                "claim": v.claim.clean_text,
                "status": v.status,
                "evidence_document_id": v.evidence_document_id,
                "evidence_text": v.evidence_text,
            }
            for v in result.hallucinations
        ],
        "corrections": [
            {
                "original": c.original,
                "corrected": c.corrected,
                "evidence_document_id": c.evidence_document_id,
            }
            for c in result.corrections
        ],
    }
