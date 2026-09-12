"""
Intent Detection  –  Phase 7 Module 5 (Step: Intent Detection)
-------------------------------------------------------------------
Classifies a normalised query into one of:

  fact         – "What is the leave policy?"
  comparison   – "Compare leave policy between 2022 and 2025"
  procedural   – "How do I apply for leave?"
  definition   – "What does 'probation period' mean?"
  summary      – "Summarize the HR handbook."
  yes_no       – "Does the company allow remote work?"
  other        – anything that doesn't match the above patterns

Two interchangeable classification methods (config: INTENT_DETECTION_METHOD):
  "heuristic" – fast, deterministic, regex/keyword-based (default; no LLM
                round-trip, so it's safe on the hot query path).
  "llm"       – few-shot prompt sent to the configured chat model
                (app.services.llm_service.get_llm) for higher-nuance intent
                classification. Falls back to the heuristic result if the
                LLM call fails or returns something unparseable.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

VALID_INTENTS = ("fact", "comparison", "procedural", "definition", "summary", "yes_no", "greeting", "other")


@dataclass
class IntentResult:
    intent: str
    confidence: float
    method: str   # "heuristic" | "llm"


# ── Heuristic classifier ───────────────────────────────────────────────────────

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|greetings|good morning|good afternoon|good evening|howdy|hi there|hello there)\b[!.?]*$",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|differ(?:s|ence)?|"
    r"which is (?:better|higher|lower|larger|smaller)|older (?:vs|and)|"
    r"between .+ and .+)\b",
    re.IGNORECASE,
)
_PROCEDURAL_RE = re.compile(
    r"^(how (?:do|can|should) i|how to|what (?:is|are) the (?:steps?|process|procedure)"
    r"|steps? (?:to|for)|process for|procedure for)\b",
    re.IGNORECASE,
)
_DEFINITION_RE = re.compile(
    r"^(what (?:is|are) (?:the )?(?:definition|meaning) of|define\b|"
    r"what does .+ mean|what is meant by)\b",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"\b(summar(?:y|ize|ise)|give me an overview|overview of|tl;?dr|"
    r"in (?:brief|short)|tell me about)\b",
    re.IGNORECASE,
)
_YES_NO_RE = re.compile(
    r"^(is|are|does|do|did|can|could|will|would|should|has|have|was|were)\b",
    re.IGNORECASE,
)
_FACT_RE = re.compile(
    r"^(what|who|when|where|which|how many|how much|why)\b", re.IGNORECASE
)


def _classify_heuristic(normalized_query: str) -> IntentResult:
    q = normalized_query.strip()

    if _GREETING_RE.match(q):
        return IntentResult("greeting", 0.95, "heuristic")
    if _COMPARISON_RE.search(q):
        return IntentResult("comparison", 0.9, "heuristic")
    if _PROCEDURAL_RE.match(q):
        return IntentResult("procedural", 0.85, "heuristic")
    if _DEFINITION_RE.match(q):
        return IntentResult("definition", 0.85, "heuristic")
    if _SUMMARY_RE.search(q):
        return IntentResult("summary", 0.8, "heuristic")
    if _FACT_RE.match(q):
        return IntentResult("fact", 0.75, "heuristic")
    if _YES_NO_RE.match(q):
        return IntentResult("yes_no", 0.7, "heuristic")
    return IntentResult("other", 0.4, "heuristic")


# ── Few-shot LLM classifier ─────────────────────────────────────────────────────

_FEW_SHOT_PROMPT = """\
Classify the user's question into EXACTLY ONE of these intents:
fact, comparison, procedural, definition, summary, yes_no, other

Examples:
Q: What is the leave policy?
Intent: fact

Q: Compare leave policy between 2022 and 2025
Intent: comparison

Q: How do I apply for annual leave?
Intent: procedural

Q: What does "probation period" mean?
Intent: definition

Q: Summarize the HR handbook.
Intent: summary

Q: Does the company allow remote work?
Intent: yes_no

Now classify this question. Reply with ONLY the intent word, nothing else.

Q: {question}
Intent:"""


async def _classify_llm(normalized_query: str) -> Optional[IntentResult]:
    try:
        from app.services.llm_service import get_llm
        llm = get_llm()
        response = await llm.ainvoke(_FEW_SHOT_PROMPT.format(question=normalized_query))
        raw = (response.content if hasattr(response, "content") else str(response)).strip().lower()
        # Extract the first token that matches a known intent label
        for intent in VALID_INTENTS:
            if intent in raw:
                return IntentResult(intent, settings.intent_llm_confidence, "llm")
        logger.warning("[IntentClassifier] LLM returned unparseable intent: %r", raw)
        return None
    except Exception as exc:
        logger.warning("[IntentClassifier] LLM classification failed, falling back: %s", exc)
        return None


# ── Public entry point ───────────────────────────────────────────────────────────

async def classify_intent(normalized_query: str) -> IntentResult:
    """
    Classify a normalised query's intent using the configured method.

    Always returns a result — the LLM method transparently falls back to
    the heuristic classifier on any failure.
    """
    if settings.intent_detection_method.lower() == "llm":
        result = await _classify_llm(normalized_query)
        if result is not None:
            return result
    return _classify_heuristic(normalized_query)
