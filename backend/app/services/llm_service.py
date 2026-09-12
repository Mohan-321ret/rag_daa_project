"""
LLM Service  –  the platform's centralized LLM Provider Manager
------------------------------------------------------------------
Admin Panel: LLM and Model Switching — every LLM call anywhere in this
app (enterprise_llm_service.generate_answer, intent_classifier's few-shot
classification, the basic /generate debug endpoint) resolves its
provider/model through get_llm() -> get_active_config() below. Nothing
else in the codebase reads settings.llm_provider or builds a LangChain
chat model directly — that's the "do not duplicate LLM logic, create a
centralized LLM provider manager" requirement, satisfied by having exactly
one module own it.

Provider abstraction: a small registry (_PROVIDER_BUILDERS) maps a
provider key ("ollama"/"openai"/"groq") to a builder function. Adding a
new provider is register_provider("azure_openai", build_fn) — no existing
code path changes. Models are NEVER hardcoded to a fixed list (Llama/
Mistral/Gemma/Qwen are just examples) — `model` is always a free-text
string resolved from admin configuration.

Config source of truth: get_active_config() reads the admin-configured
LLMProviderConfig row with status='active' AND is_current=True from
PostgreSQL (app/models/llm_provider.py). If none exists yet (fresh
install, before any admin has used the Admin Panel), it falls back to the
.env-driven settings.llm_provider/ollama_model/openai_model/groq_model —
this is what let every pre-Phase-8 code path keep working unmodified.

Secrets: API keys are NEVER stored in the LLMProviderConfig row, only the
NAME of an environment variable to read at call time (os.environ.get) —
see app/models/llm_provider.py's module docstring for the full rationale.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, List, Optional

import httpx
from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Model resolution (Ollama alias registry) ───────────────────────────────

def resolve_ollama_model(model: Optional[str] = None) -> str:
    """
    Resolve a caller-supplied alias or raw tag to a concrete Ollama model tag.

    An unrecognised alias is passed through unchanged (treated as an exact
    Ollama tag, e.g. "gemma3:4b" or "llama3:70b").
    """
    requested = (model or settings.llm_default_model_alias or settings.ollama_model).strip()
    return settings.llm_model_registry_map.get(requested.lower(), requested)


# ── Availability checking ─────────────────────────────────────────────────────

def list_ollama_models() -> List[str]:
    """Query the local Ollama daemon for installed model tags. [] if unreachable."""
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:
        logger.warning("[LLMService] Could not reach Ollama to list models: %s", exc)
        return []


def is_ollama_model_available(tag: str, installed: Optional[List[str]] = None) -> bool:
    """
    Check whether *tag* (or its base name, ignoring the ":variant" suffix)
    is among the models actually pulled on the local Ollama daemon.
    """
    installed = installed if installed is not None else list_ollama_models()
    if not installed:
        return False
    base = tag.split(":")[0]
    return any(t == tag or t.split(":")[0] == base for t in installed)


# ── Provider registry (the "abstraction" the extension point hangs off) ───────

BuilderFn = Callable[
    [str, Optional[str], Optional[str], float, Optional[int], Optional[int]],
    BaseChatModel,
]
# (model, endpoint, api_key, temperature, max_tokens, context_window) -> BaseChatModel


def _build_openai(model, endpoint, api_key, temperature, max_tokens, context_window) -> BaseChatModel:
    from langchain_openai import ChatOpenAI
    kwargs: dict = {"model": model, "api_key": api_key, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if endpoint:
        kwargs["base_url"] = endpoint
    return ChatOpenAI(**kwargs)


def _build_groq(model, endpoint, api_key, temperature, max_tokens, context_window) -> BaseChatModel:
    from langchain_groq import ChatGroq
    resolved_api_key = api_key or os.environ.get("GROQ_API_KEY") or settings.groq_api_key
    kwargs: dict = {"model": model, "groq_api_key": resolved_api_key, "temperature": temperature}
    # Cap max_tokens to <= 500 to comply with Groq on-demand tier OTPM limits
    capped_tokens = max_tokens if (max_tokens and max_tokens <= 500) else 500
    kwargs["max_tokens"] = capped_tokens
    if endpoint:
        kwargs["base_url"] = endpoint
    return ChatGroq(**kwargs)


def _build_ollama(model, endpoint, api_key, temperature, max_tokens, context_window) -> BaseChatModel:
    from langchain_ollama import ChatOllama
    kwargs: dict = {"model": model, "base_url": endpoint or settings.ollama_base_url, "temperature": temperature}
    if max_tokens:
        kwargs["num_predict"] = max_tokens
    if context_window:
        kwargs["num_ctx"] = context_window
    return ChatOllama(**kwargs)


_PROVIDER_BUILDERS: Dict[str, BuilderFn] = {
    "openai": _build_openai,
    "groq": _build_groq,
    "ollama": _build_ollama,
}


def register_provider(key: str, builder: BuilderFn) -> None:
    """
    Extension point for "other providers supported by the existing
    architecture" — register a new provider's builder without touching
    get_llm(), get_active_config(), or any caller. `builder` receives
    (model, endpoint, api_key, temperature, max_tokens, context_window)
    and must return a LangChain BaseChatModel.
    """
    _PROVIDER_BUILDERS[key.lower()] = builder
    build_llm.cache_clear()


def registered_providers() -> List[str]:
    """Every provider key currently available to select in the Admin Panel."""
    return sorted(_PROVIDER_BUILDERS.keys())


@lru_cache(maxsize=16)
def build_llm(
    provider: str, model: str, endpoint: Optional[str], api_key: Optional[str],
    temperature: float, max_tokens: Optional[int], context_window: Optional[int],
) -> BaseChatModel:
    """
    Construct (and cache) a LangChain chat model for an EXACT set of
    parameters. Cached on the full parameter tuple (not just provider+model)
    so editing a saved config's temperature/max_tokens/endpoint/key always
    produces a fresh instance — no manual cache invalidation needed when an
    admin edits or switches configs.

    Public (not `_`-prefixed) because llm_config_service.py's
    "test connection" action calls it directly against a config that may
    not be the active one — get_llm() below is the request-path shortcut
    that resolves the ACTIVE config first.
    """
    builder = _PROVIDER_BUILDERS.get(provider.lower())
    if builder is None:
        raise ValueError(f"Unknown LLM provider '{provider}'. Registered providers: {registered_providers()}")
    return builder(model, endpoint, api_key, temperature, max_tokens, context_window)


# ── Active configuration resolution ────────────────────────────────────────

@dataclass
class ResolvedLLMConfig:
    provider: str
    model: str
    endpoint: Optional[str]
    api_key: Optional[str]           # resolved from os.environ — never persisted/logged/returned
    temperature: float
    max_tokens: Optional[int]
    context_window: Optional[int]
    source: str                       # "db" | "settings-fallback"


def _settings_fallback_config() -> ResolvedLLMConfig:
    """
    Pre-Phase-8 behavior: no admin-managed config exists yet (fresh
    install, or the seed row was deleted), so fall back to the .env-driven
    settings that used to be the only source of truth.
    """
    provider = settings.llm_provider.lower()
    if provider == "openai":
        return ResolvedLLMConfig(
            "openai", settings.openai_model, None, settings.openai_api_key or None,
            settings.llm_temperature, None, None, "settings-fallback",
        )
    if provider == "groq":
        return ResolvedLLMConfig(
            "groq", settings.groq_model, None, settings.groq_api_key or None,
            settings.llm_temperature, None, None, "settings-fallback",
        )
    return ResolvedLLMConfig(
        "ollama", settings.ollama_model, settings.ollama_base_url, None,
        settings.llm_temperature, None, None, "settings-fallback",
    )


def get_active_config(db: Optional[Session] = None) -> ResolvedLLMConfig:
    """
    The single source of truth for "which LLM should serve requests right
    now". Every caller in this file (and therefore every LLM call in the
    app) goes through this.

    `db` is optional: most callers (intent_classifier, the /generate debug
    route) have no DB session in scope, so when omitted this opens and
    closes its own short-lived session — callers never need to thread a
    session through just to reach the LLM.
    """
    owns_session = db is None
    if owns_session:
        from app.db.database import SessionLocal
        db = SessionLocal()
    try:
        from app.models.llm_provider import LLMProviderConfig
        row = (
            db.query(LLMProviderConfig)
            .filter(LLMProviderConfig.is_current.is_(True), LLMProviderConfig.status == "active")
            .first()
        )
        if row is None:
            return _settings_fallback_config()
        api_key = None
        if row.api_key_env_var:
            api_key = os.environ.get(row.api_key_env_var) or getattr(settings, row.api_key_env_var.lower(), None)
        return ResolvedLLMConfig(
            provider=row.provider,
            model=row.model,
            endpoint=row.endpoint,
            api_key=api_key,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            context_window=row.context_window,
            source="db",
        )
    except Exception as exc:  # pragma: no cover — e.g. DB unreachable
        logger.warning("[LLMService] Could not load active LLM config from DB, using settings fallback: %s", exc)
        return _settings_fallback_config()
    finally:
        if owns_session:
            db.close()


# ── Model factory (request path) ────────────────────────────────────────────

def get_llm(model: Optional[str] = None, db: Optional[Session] = None) -> BaseChatModel:
    """
    Return a cached LangChain chat model for the currently ACTIVE provider
    (see get_active_config).

    Args:
        model: Optional per-call override. For Ollama this may be an alias
               ("llama3"/"gemma"/"mistral"/"qwen") or a raw tag
               ("llama3:70b"); ignored for every other provider, whose
               model comes entirely from the active config — same
               documented behavior as before Phase 8.
        db:    Optional session to resolve the active config with (see
               get_active_config).
    """
    cfg = get_active_config(db)
    resolved_model = cfg.model
    if cfg.provider == "ollama":
        resolved_model = resolve_ollama_model(model or cfg.model)
    return build_llm(cfg.provider, resolved_model, cfg.endpoint, cfg.api_key, cfg.temperature, cfg.max_tokens, cfg.context_window)


async def generate_response(prompt: str, model: Optional[str] = None) -> str:
    """Simple wrapper: send a prompt and return the string response with Ollama fallback."""
    import re
    cfg = get_active_config()
    try:
        llm = get_llm(model)
        response = await llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip() or text
    except Exception as exc:
        if cfg.provider != "ollama":
            logger.warning("[LLMService] Primary provider '%s' failed: %s — falling back to Ollama", cfg.provider, exc)
            fallback_model = resolve_ollama_model("llama3")
            fallback_llm = build_llm("ollama", fallback_model, settings.ollama_base_url, None, cfg.temperature, cfg.max_tokens, cfg.context_window)
            response = await fallback_llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip() or text
        raise
