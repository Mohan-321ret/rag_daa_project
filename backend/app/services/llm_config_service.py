"""
LLM Config Service  –  Admin Panel: LLM and Model Switching
----------------------------------------------------------------------
CRUD + lifecycle operations (activate/deactivate/switch-active) for
LLMProviderConfig rows, plus "test model connection". This is the
bookkeeping layer — the actual "build a LangChain chat model" logic stays
centralized in app/services/llm_service.py (the provider manager); this
file only ever calls into that, never duplicates it.

No background-job machinery here (unlike Phases 6/7's IngestionJob/
ReindexJob) — every operation below is a fast, bounded, synchronous DB
write or a single short-timeout network call, not the kind of
"expensive operation" those phases' async-job requirement was about.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.llm_provider import LLMProviderConfig
from app.services import llm_service

logger = logging.getLogger(__name__)

# Ollama can take 10-15s+ on a cold model swap (loading a different model
# into memory) before it even starts generating — verified directly against
# this dev machine's Ollama daemon. 15s was too tight and produced false
# "connection failed" timeouts for a model that actually works fine once
# warm; 30s gives real cold-starts room without waiting forever on a
# genuinely broken endpoint.
TEST_CONNECTION_TIMEOUT_S = 30.0


def list_configs(db: Session) -> list[LLMProviderConfig]:
    return db.query(LLMProviderConfig).order_by(LLMProviderConfig.created_at.desc()).all()


def get_config_or_404(db: Session, config_id: str) -> LLMProviderConfig:
    config = db.query(LLMProviderConfig).filter(LLMProviderConfig.id == config_id).first()
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"LLM provider config '{config_id}' not found.")
    return config


def api_key_configured(config: LLMProviderConfig) -> bool:
    """Whether the referenced env var currently resolves to a non-empty value — never returns the value itself."""
    return bool(config.api_key_env_var and os.environ.get(config.api_key_env_var))


def create_config(
    db: Session, *, name: str, provider: str, model: str,
    endpoint: Optional[str], api_key_env_var: Optional[str],
    temperature: float, max_tokens: Optional[int], context_window: Optional[int],
    created_by_user_id,
) -> LLMProviderConfig:
    provider = provider.lower().strip()
    if provider not in llm_service.registered_providers():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider '{provider}'. Registered providers: {llm_service.registered_providers()}",
        )
    if db.query(LLMProviderConfig).filter(LLMProviderConfig.name == name).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A config named '{name}' already exists.")

    config = LLMProviderConfig(
        name=name, provider=provider, model=model, endpoint=endpoint or None,
        api_key_env_var=api_key_env_var or None, temperature=temperature,
        max_tokens=max_tokens, context_window=context_window,
        status="inactive", is_current=False, created_by=created_by_user_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    logger.info("[LLMConfig] ➕ Created '%s' (provider=%s model=%s)", name, provider, model)
    return config


def update_config(db: Session, config: LLMProviderConfig, **fields) -> LLMProviderConfig:
    """Edits model/endpoint/api_key_env_var/temperature/max_tokens/context_window/name — never `provider` (immutable after creation; add a new config to switch providers) or `status`/`is_current` (dedicated action endpoints own those transitions)."""
    if "name" in fields and fields["name"] and fields["name"] != config.name:
        if db.query(LLMProviderConfig).filter(LLMProviderConfig.name == fields["name"]).first() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A config named '{fields['name']}' already exists.")
    for key, value in fields.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    db.commit()
    db.refresh(config)
    logger.info("[LLMConfig] ✏️  Configured '%s'", config.name)
    return config


def activate_config(db: Session, config: LLMProviderConfig) -> None:
    config.status = "active"
    db.commit()
    logger.info("[LLMConfig] ✅ Activated '%s'", config.name)


def deactivate_config(db: Session, config: LLMProviderConfig) -> None:
    if config.is_current:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This config is currently serving traffic — switch the active model to another config before deactivating it.",
        )
    config.status = "inactive"
    db.commit()
    logger.info("[LLMConfig] 🛑 Deactivated '%s'", config.name)


def switch_active(db: Session, config: LLMProviderConfig) -> None:
    """Makes *config* THE model serving RAG traffic — the moment "when an LLM is switched" actually takes effect."""
    if config.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This config must be activated before it can be switched to. Activate it first.",
        )
    db.query(LLMProviderConfig).filter(LLMProviderConfig.is_current.is_(True)).update(
        {"is_current": False}, synchronize_session=False,
    )
    config.is_current = True
    db.commit()
    llm_service.build_llm.cache_clear()
    logger.info("[LLMConfig] 🔀 Switched active model to '%s' (provider=%s model=%s)", config.name, config.provider, config.model)


@dataclass
class TestConnectionResult:
    success: bool
    message: str
    latency_ms: Optional[float]
    model_used: str


def _sanitize(message: str, secret: Optional[str]) -> str:
    if secret:
        message = message.replace(secret, "***")
    return message[:300]


async def test_connection(config: LLMProviderConfig) -> TestConnectionResult:
    """
    Attempts a real, minimal generation call against *config* — proves
    end-to-end reachability (network + auth + model availability), not
    just "the row looks well-formed". Never raises; always returns a
    result the caller can show directly to an admin.
    """
    api_key = os.environ.get(config.api_key_env_var) if config.api_key_env_var else None
    if config.api_key_env_var and not api_key:
        return TestConnectionResult(
            success=False,
            message=f"Environment variable '{config.api_key_env_var}' is not set (or empty) on this server.",
            latency_ms=None, model_used=config.model,
        )

    start = time.monotonic()
    try:
        llm = llm_service.build_llm(
            config.provider, config.model, config.endpoint, api_key,
            config.temperature, config.max_tokens, config.context_window,
        )
        response = await asyncio.wait_for(llm.ainvoke("Reply with exactly one word: OK"), timeout=TEST_CONNECTION_TIMEOUT_S)
        latency_ms = (time.monotonic() - start) * 1000
        text = response.content if hasattr(response, "content") else str(response)
        return TestConnectionResult(
            success=True, message=f"Connected successfully. Sample response: {str(text)[:80]!r}",
            latency_ms=round(latency_ms, 1), model_used=config.model,
        )
    except asyncio.TimeoutError:
        return TestConnectionResult(
            success=False, message=f"Timed out after {TEST_CONNECTION_TIMEOUT_S:.0f}s waiting for a response.",
            latency_ms=round((time.monotonic() - start) * 1000, 1), model_used=config.model,
        )
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning("[LLMConfig] Test connection failed for '%s': %s", config.name, exc)
        return TestConnectionResult(
            success=False, message=_sanitize(str(exc), api_key), latency_ms=latency_ms, model_used=config.model,
        )
