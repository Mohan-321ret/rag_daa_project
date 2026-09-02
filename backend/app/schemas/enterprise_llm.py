"""
Pydantic schemas for the Enterprise LLM API (Module 8 – Phase 10).
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel


class ModelInfo(BaseModel):
    alias: str
    tag: str
    available: bool   # whether this tag is actually pulled on the local Ollama daemon


class ModelsResponse(BaseModel):
    provider: str
    default_alias: str
    default_tag: str
    models: List[ModelInfo]
    installed_raw: List[str]   # every tag Ollama reports, including ones not in the alias registry
