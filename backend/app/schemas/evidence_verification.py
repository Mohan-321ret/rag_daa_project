"""
Pydantic schemas for the Evidence Verification API (Module 9 – Phase 11).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    answer: str = Field(
        ..., min_length=1, max_length=8192,
        description="A generated answer to independently fact-check against the knowledge base.",
        examples=["Leave policy is 30 days."],
    )
    document_id: Optional[str] = Field(
        default=None,
        description="If set, scope evidence re-retrieval (and any correction) to this document only.",
    )


class ClaimVerificationOut(BaseModel):
    claim: str
    is_quantitative: bool
    status: str                              # supported | contradicted | unverifiable
    claim_values: List[str]
    evidence_document_id: Optional[str] = None
    evidence_text: Optional[str] = None
    evidence_values: List[str] = Field(default_factory=list)
    statement_similarity: float = 0.0


class CorrectionOut(BaseModel):
    original: str
    corrected: str
    evidence_document_id: str


class VerifyResponse(BaseModel):
    original_answer: str
    final_answer: str
    was_rewritten: bool
    confidence_score: float
    claims_total: int
    claims_checked: int
    verifications: List[ClaimVerificationOut]
    hallucinations: List[ClaimVerificationOut]
    corrections: List[CorrectionOut] = Field(default_factory=list)
