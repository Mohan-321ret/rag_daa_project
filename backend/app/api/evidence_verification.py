"""
Evidence Verification API Router  –  Phase 11 Module 9
------------------------------------------------------------
Endpoint: POST /api/v1/verification/verify

Standalone access to the Evidence Verification pipeline (Claim Extraction
→ Retrieve Evidence Again → Fact Verification → Confidence Score →
Hallucination Detection → Rewrite Answer) — fact-checks ANY answer text
against the current knowledge base, independent of the RAG pipeline. The
same engine runs automatically inside POST /api/v1/rag/query right after
the LLM generates its answer (Phase 10).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role
from app.db.database import get_db
from app.models.user import User
from app.schemas.evidence_verification import (
    ClaimVerificationOut,
    CorrectionOut,
    VerifyRequest,
    VerifyResponse,
)
from app.services.auth_service import current_role, require_permission
from app.services.chunk_access_service import build_chunk_access_context
from app.services.evidence_verification_service import VerificationResult, verify_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/verification", tags=["Evidence Verification (Module 9)"])


def _to_claim_out(v) -> ClaimVerificationOut:
    return ClaimVerificationOut(
        claim=v.claim.clean_text,
        is_quantitative=v.claim.is_quantitative,
        status=v.status,
        claim_values=v.claim.values,
        evidence_document_id=v.evidence_document_id,
        evidence_text=v.evidence_text,
        evidence_values=v.evidence_values,
        statement_similarity=v.statement_similarity,
    )


@router.post(
    "/verify",
    response_model=VerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Fact-check an answer against the knowledge base",
    description=(
        "Runs the Evidence Verification pipeline on arbitrary answer text:\n\n"
        "**Claim Extraction → Retrieve Evidence Again → Fact Verification → "
        "Confidence Score → Hallucination Detection → Rewrite Answer**\n\n"
        "Example: `{\"answer\": \"Leave policy is 30 days.\"}` against a "
        "knowledge base whose actual policy is 25 days will be flagged as "
        "contradicted and rewritten with the correct, cited value."
    ),
)
def verify(
    body: VerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    caller_role: Role = Depends(current_role),
) -> VerifyResponse:
    access_ctx = build_chunk_access_context(db, current_user, caller_role)
    result: VerificationResult = verify_answer(db, body.answer, access_ctx, document_id=body.document_id)

    return VerifyResponse(
        original_answer=result.original_answer,
        final_answer=result.final_answer,
        was_rewritten=result.was_rewritten,
        confidence_score=result.confidence_score,
        claims_total=result.claims_total,
        claims_checked=result.claims_checked,
        verifications=[_to_claim_out(v) for v in result.verifications],
        hallucinations=[_to_claim_out(v) for v in result.hallucinations],
        corrections=[
            CorrectionOut(
                original=c.original, corrected=c.corrected,
                evidence_document_id=c.evidence_document_id,
            )
            for c in result.corrections
        ],
    )
