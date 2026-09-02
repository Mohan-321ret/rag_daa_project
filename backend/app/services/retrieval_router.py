"""
Retrieval Router  –  Phase 8 Module 6 (Router)
--------------------------------------------------
Instead of always going to the vector store, this router looks at what
Phase 7's Query Intelligence module already learned about the question
(intent, entities, complexity) plus two extra pattern checks, and picks
ONE of four retrieval routes:

  Question ─→ Router ─→ Choose Retrieval
                          ├─ Fact                  → Vector
                          ├─ Exact Policy Number    → BM25
                          ├─ Relationship            → Knowledge Graph
                          └─ Complex                → Hybrid (BM25+Vector+Graph)

Priority order (first match wins): an exact policy/clause number is the
strongest, most specific signal, so it's checked before anything else;
relationship phrasing is checked next; only then do the broader
intent/complexity signals from Phase 7 pick "hybrid" vs. the "vector"
default.

Phase 12 (Module 10, Continuous Learning) adds one more step AFTER the
deterministic decision above: if a `db` session is supplied and the chosen
route has a confirmed history of poor 👍/👎 satisfaction for this intent,
it's escalated to "hybrid" — see routing_improvement_service.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.query_intelligence_service import QueryAnalysis

logger = logging.getLogger(__name__)

VALID_ROUTES = ("vector", "bm25", "graph", "hybrid")


@lru_cache(maxsize=1)
def _policy_number_re() -> re.Pattern:
    return re.compile(settings.policy_number_pattern, re.IGNORECASE)


@dataclass
class RouteDecision:
    route: str                            # vector | bm25 | graph | hybrid
    reason: str                           # human-readable explanation
    signals: List[str] = field(default_factory=list)  # matched trigger(s)


def _matched_relationship_keyword(normalized_query: str) -> str | None:
    q = normalized_query.lower()
    for kw in settings.relationship_keyword_list:
        if kw in q:
            return kw
    return None


def _has_relationship_entities(analysis: QueryAnalysis) -> bool:
    """Two or more non-temporal named entities is itself a relationship signal
    ("Acme Corp and Globex Inc" implies asking how they relate)."""
    RELATIONAL_LABELS = {"PERSON", "ORG", "GPE", "NORP", "FAC", "LAW", "EVENT", "PRODUCT"}
    relational_entities = [e for e in analysis.entities if e.label in RELATIONAL_LABELS]
    return len(relational_entities) >= 2


def _base_decision(analysis: QueryAnalysis) -> RouteDecision:
    """The deterministic Phase 8 routing rules, unaffected by feedback."""
    q = analysis.normalized_query

    # ── 1. Exact Policy Number → BM25 ──────────────────────────────────────────
    policy_match = _policy_number_re().search(q)
    if policy_match:
        return RouteDecision(
            route="bm25",
            reason=f"Exact policy/clause reference detected: '{policy_match.group(0)}'",
            signals=[policy_match.group(0)],
        )

    # ── 2. Relationship → Knowledge Graph ──────────────────────────────────────
    rel_keyword = _matched_relationship_keyword(q)
    if rel_keyword or _has_relationship_entities(analysis):
        signal = rel_keyword or "multiple named entities"
        return RouteDecision(
            route="graph",
            reason=f"Relationship signal detected: '{signal}'",
            signals=[signal],
        )

    # ── 3. Complex / Comparison → Hybrid (BM25 + Vector + Graph) ───────────────
    if analysis.intent.intent == "comparison" or analysis.complexity.level == "complex":
        signal = (
            "comparison intent" if analysis.intent.intent == "comparison"
            else f"complex query (score={analysis.complexity.score})"
        )
        return RouteDecision(
            route="hybrid",
            reason=f"Query needs multi-source evidence: {signal}",
            signals=[signal],
        )

    # ── 4. Fact (default) → Vector ──────────────────────────────────────────────
    return RouteDecision(
        route="vector",
        reason=f"Straightforward '{analysis.intent.intent}' query – semantic search suffices.",
        signals=[analysis.intent.intent],
    )


def decide_route(analysis: QueryAnalysis, db: Optional[Session] = None) -> RouteDecision:
    """
    Choose a retrieval route for an already-analyzed query (Phase 7 output).

    Args:
        db: Optional SQLAlchemy session. When supplied, Phase 12's Improve
            Routing step gets a chance to escalate the deterministic choice
            to "hybrid" if it has a confirmed history of poor user
            satisfaction for this intent. Omitting `db` (e.g. in unit
            tests) always yields the pure Phase 8 decision.

    Returns:
        RouteDecision naming exactly one of vector/bm25/graph/hybrid, with
        an explanation for observability/debugging.
    """
    decision = _base_decision(analysis)

    if db is not None:
        from app.services.routing_improvement_service import suggest_route_override
        override = suggest_route_override(db, decision.route, analysis.intent.intent)
        if override:
            return RouteDecision(
                route=override,
                reason=(
                    f"{decision.reason} — escalated to '{override}': historical "
                    f"user feedback shows '{decision.route}' underperforms for "
                    f"'{analysis.intent.intent}' queries."
                ),
                signals=decision.signals + ["feedback_escalation"],
            )

    return decision
