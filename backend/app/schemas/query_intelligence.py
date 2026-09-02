"""
Pydantic schemas for the Query Intelligence Module API (Module 5 – Phase 7).
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class QueryAnalyzeRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=2048,
        examples=["Compare leave policy between 2022 and 2025"],
    )
    top_k: int = Field(
        default=5, ge=1, le=20,
        description="Baseline retrieval breadth; may be widened by the complexity analyzer.",
    )


class EntityOut(BaseModel):
    text: str
    label: str
    start: int
    end: int


class IntentOut(BaseModel):
    intent: str        # fact | comparison | procedural | definition | summary | yes_no | other
    confidence: float
    method: str         # heuristic | llm


class ComplexityOut(BaseModel):
    level: str          # simple | medium | complex
    score: float
    factors: dict


class TemporalOut(BaseModel):
    has_temporal: bool
    scope: str           # none | current | historical | point_in_time | range_comparison
    expressions: List[str]
    years: List[int]


class QueryAnalysisResponse(BaseModel):
    raw_query: str
    normalized_query: str
    sub_questions: List[str]
    intent: IntentOut
    entities: List[EntityOut]
    complexity: ComplexityOut
    temporal: TemporalOut
    suggested_top_k: int
