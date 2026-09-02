"""
Pydantic schemas for the LLM Provider Config API — Admin Panel: LLM and
Model Switching.

api_key_env_var carries only the NAME of an environment variable — there
is no field anywhere in this module for a raw secret value, by design
("Sensitive API keys must NEVER be returned to the frontend").
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LLMProviderConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    endpoint: Optional[str] = None
    api_key_env_var: Optional[str] = None
    api_key_configured: bool = False   # computed: does that env var currently resolve to a value? (never the value itself)
    temperature: float
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None
    status: str
    is_current: bool
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LLMProviderListResponse(BaseModel):
    total: int
    providers: list[LLMProviderConfigOut]


class LLMProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., description="Must be a registered provider key — see GET /llm-providers/registry")
    model: str = Field(..., min_length=1, max_length=128)
    endpoint: Optional[str] = None
    api_key_env_var: Optional[str] = Field(None, description="Name of an environment variable holding the API key — never the key itself")
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None


class LLMProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    model: Optional[str] = Field(None, min_length=1, max_length=128)
    endpoint: Optional[str] = None
    api_key_env_var: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None


class ProviderRegistryResponse(BaseModel):
    providers: list[str]


class SwitchActiveResponse(BaseModel):
    success: bool = True
    id: str
    name: str
    provider: str
    model: str
    message: str = "Active model switched. The RAG pipeline will use it immediately."


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[float] = None
    model_used: str
