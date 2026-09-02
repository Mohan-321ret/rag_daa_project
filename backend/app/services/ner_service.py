"""
NER Service  –  Phase 7 Module 5 (Step: NER)
------------------------------------------------
Wraps spaCy's small English pipeline to extract named entities from a
user query (dates, organisations, people, quantities, etc.). The model is
loaded once and cached for the lifetime of the process, mirroring how
embedding_service caches its SentenceTransformer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """One named entity extracted from a query."""
    text: str
    label: str        # spaCy entity label, e.g. DATE, ORG, PERSON, GPE, CARDINAL
    start: int         # character offset (start) in the source text
    end: int           # character offset (end) in the source text


@lru_cache(maxsize=1)
def _get_nlp():
    """Load and cache the spaCy pipeline."""
    import spacy
    try:
        return spacy.load(settings.spacy_model)
    except OSError:
        logger.warning(
            "[NERService] spaCy model '%s' not found – run "
            "`python -m spacy download %s`. Falling back to a blank English "
            "pipeline (NER disabled).",
            settings.spacy_model, settings.spacy_model,
        )
        return spacy.blank("en")


def extract_entities(text: str) -> List[Entity]:
    """
    Extract named entities from *text*.

    Returns an empty list if the text is empty or the spaCy model has no
    NER component available (blank-pipeline fallback).
    """
    if not text or not text.strip():
        return []

    nlp = _get_nlp()
    if "ner" not in nlp.pipe_names:
        return []

    doc = nlp(text)
    entities = [
        Entity(text=ent.text, label=ent.label_, start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
    ]
    logger.debug("[NERService] Extracted %d entities from query.", len(entities))
    return entities
