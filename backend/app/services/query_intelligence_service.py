"""
Query Intelligence Engine  –  Phase 7 Module 5 (Orchestrator)
------------------------------------------------------------------
Wires all steps of the query understanding pipeline:

  Query Parser        – normalize()                    [query_parser]
  Intent Detection     – Fact | Comparison | ...         [intent_classifier]
  NER                  – spaCy entity extraction         [ner_service]
  Complexity Analyzer  – Simple | Medium | Complex        [complexity_analyzer]
  Temporal Detection   – today/old/previous/2023/...     [temporal_detector]

Entry point: analyze_query(raw_query) -> QueryAnalysis

The result is consumed by the RAG pipeline (Phase 5) to adapt retrieval
(e.g. widen top_k for complex/comparison queries) and is also exposed
standalone via POST /api/v1/query/analyze for inspection/testing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from app.core.config import settings
from app.services.complexity_analyzer import ComplexityResult, analyze_complexity
from app.services.intent_classifier import IntentResult, classify_intent
from app.services.ner_service import Entity, extract_entities
from app.services.query_parser import ParsedQuery, parse_query
from app.services.temporal_detector import TemporalResult, detect_temporal

logger = logging.getLogger(__name__)


@dataclass
class QueryAnalysis:
    """Full output of the Query Intelligence pipeline for one query."""
    raw_query: str
    normalized_query: str
    sub_questions: List[str]
    intent: IntentResult
    entities: List[Entity]
    complexity: ComplexityResult
    temporal: TemporalResult
    suggested_top_k: int


def _suggest_top_k(default_top_k: int, complexity_level: str) -> int:
    """Scale FAISS retrieval breadth to the query's estimated complexity."""
    if complexity_level == "complex":
        return max(default_top_k, settings.complexity_top_k_complex)
    if complexity_level == "medium":
        return max(default_top_k, settings.complexity_top_k_medium)
    return default_top_k


async def analyze_query(raw_query: str, default_top_k: int = 5) -> QueryAnalysis:
    """
    Run the full query-understanding pipeline on a raw user question.

    Args:
        raw_query:     The user's original natural-language question.
        default_top_k: The caller's requested top_k (used as a floor when
                       suggesting a retrieval breadth for complex queries).

    Returns:
        QueryAnalysis combining parsing, intent, entities, complexity and
        temporal scope.
    """
    # ── Step: Query Parser (normalize) ────────────────────────────────────────
    parsed: ParsedQuery = parse_query(raw_query)

    # ── Step: NER (spaCy) ──────────────────────────────────────────────────────
    entities: List[Entity] = extract_entities(parsed.normalized)

    # ── Step: Temporal Detection ──────────────────────────────────────────────
    temporal: TemporalResult = detect_temporal(parsed.normalized)

    # ── Step: Intent Detection (heuristic or few-shot LLM) ────────────────────
    intent: IntentResult = await classify_intent(parsed.normalized)

    # ── Step: Complexity Analyzer ─────────────────────────────────────────────
    complexity: ComplexityResult = analyze_complexity(
        word_count=parsed.word_count,
        sub_question_count=len(parsed.sub_questions),
        entity_count=len(entities),
        intent=intent.intent,
        has_temporal_range=(temporal.scope == "range_comparison"),
        normalized_query=parsed.normalized,
    )

    suggested_top_k = _suggest_top_k(default_top_k, complexity.level)

    logger.info(
        "[QueryIntelligence] q='%s...' intent=%s(%s) complexity=%s(%.2f) "
        "temporal=%s entities=%d top_k=%d",
        parsed.normalized[:60], intent.intent, intent.method,
        complexity.level, complexity.score, temporal.scope,
        len(entities), suggested_top_k,
    )

    return QueryAnalysis(
        raw_query=raw_query,
        normalized_query=parsed.normalized,
        sub_questions=parsed.sub_questions,
        intent=intent,
        entities=entities,
        complexity=complexity,
        temporal=temporal,
        suggested_top_k=suggested_top_k,
    )


def query_analysis_to_dict(analysis: QueryAnalysis) -> dict:
    """Plain-dict projection of a QueryAnalysis, shared by the /query/analyze
    and /rag/query API routers so both expose an identical JSON shape."""
    return {
        "raw_query": analysis.raw_query,
        "normalized_query": analysis.normalized_query,
        "sub_questions": analysis.sub_questions,
        "intent": {
            "intent": analysis.intent.intent,
            "confidence": analysis.intent.confidence,
            "method": analysis.intent.method,
        },
        "entities": [
            {"text": e.text, "label": e.label, "start": e.start, "end": e.end}
            for e in analysis.entities
        ],
        "complexity": {
            "level": analysis.complexity.level,
            "score": analysis.complexity.score,
            "factors": analysis.complexity.factors,
        },
        "temporal": {
            "has_temporal": analysis.temporal.has_temporal,
            "scope": analysis.temporal.scope,
            "expressions": analysis.temporal.expressions,
            "years": analysis.temporal.years,
        },
        "suggested_top_k": analysis.suggested_top_k,
    }
