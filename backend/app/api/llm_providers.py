"""
LLM Providers API Router  –  Admin Panel: LLM and Model Switching
----------------------------------------------------------------------
  GET  /llm-providers/registry              – which provider keys exist
  GET  /llm-providers/                       – view configured providers
  GET  /llm-providers/{id}                   – single config detail
  POST /llm-providers/                       – add provider
  PATCH /llm-providers/{id}                  – configure model
  POST /llm-providers/{id}/activate          – activate model
  POST /llm-providers/{id}/deactivate        – deactivate model
  POST /llm-providers/{id}/switch-active     – switch active model
  POST /llm-providers/{id}/test-connection   – test model connection

Gated by Permission.LLM_VIEW (read) / LLM_CONFIGURE (every write) — both
already existed in the Phase 2 Role & Access Matrix; LLM_CONFIGURE is held
only by PLATFORM_OWNER/SUPER_ADMIN (see permissions.py's ROLE_PERMISSIONS —
it's the one Chunk/Ingestion-style permission that was NEVER granted to
DOMAIN_MANAGER, since LLM config is inherently platform-wide, not
domain-scoped — "restrict LLM configuration to authorized roles" is
already satisfied by the existing matrix, no new domain-boundary logic
needed here the way Phase 7's full-rebuild gate needed one).

Every write endpoint logs an AuditLog row — switch-active gets its own
`llm_switched` event type since the spec calls that action out by name.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db.database import get_db
from app.models.llm_provider import LLMProviderConfig
from app.models.user import User
from app.schemas.llm_provider import (
    LLMProviderConfigOut,
    LLMProviderCreate,
    LLMProviderListResponse,
    LLMProviderUpdate,
    ProviderRegistryResponse,
    SwitchActiveResponse,
    TestConnectionResponse,
)
from app.services import llm_config_service, llm_service
from app.services.audit_service import log_audit_event
from app.services.auth_service import require_permission

router = APIRouter(prefix="/llm-providers", tags=["LLM Management"])


def _to_out(config: LLMProviderConfig) -> LLMProviderConfigOut:
    return LLMProviderConfigOut(
        id=str(config.id),
        name=config.name,
        provider=config.provider,
        model=config.model,
        endpoint=config.endpoint,
        api_key_env_var=config.api_key_env_var,
        api_key_configured=llm_config_service.api_key_configured(config),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        context_window=config.context_window,
        status=config.status,
        is_current=config.is_current,
        created_by=str(config.created_by) if config.created_by else None,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _audit(db: Session, event_type: str, actor: User, detail: str) -> None:
    log_audit_event(db, event_type=event_type, actor=actor, detail=detail)
    db.commit()


# ── GET /llm-providers/registry ─────────────────────────────────────────────

@router.get("/registry", response_model=ProviderRegistryResponse, summary="List registered provider keys")
def get_registry(_: User = Depends(require_permission(Permission.LLM_VIEW))) -> ProviderRegistryResponse:
    return ProviderRegistryResponse(providers=llm_service.registered_providers())


# ── GET /llm-providers/ ──────────────────────────────────────────────────────

@router.get("/", response_model=LLMProviderListResponse, summary="View configured providers")
def list_providers(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LLM_VIEW)),
) -> LLMProviderListResponse:
    configs = llm_config_service.list_configs(db)
    return LLMProviderListResponse(total=len(configs), providers=[_to_out(c) for c in configs])


@router.get("/{config_id}", response_model=LLMProviderConfigOut, summary="Get a single provider config")
def get_provider(
    config_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LLM_VIEW)),
) -> LLMProviderConfigOut:
    return _to_out(llm_config_service.get_config_or_404(db, config_id))


# ── POST /llm-providers/ ─────────────────────────────────────────────────────

@router.post("/", response_model=LLMProviderConfigOut, status_code=status.HTTP_201_CREATED, summary="Add a provider")
def create_provider(
    body: LLMProviderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> LLMProviderConfigOut:
    config = llm_config_service.create_config(
        db, name=body.name, provider=body.provider, model=body.model,
        endpoint=body.endpoint, api_key_env_var=body.api_key_env_var,
        temperature=body.temperature, max_tokens=body.max_tokens, context_window=body.context_window,
        created_by_user_id=current_user.id,
    )
    _audit(db, "llm_provider_added", current_user, f"name={config.name} provider={config.provider} model={config.model}")
    return _to_out(config)


# ── PATCH /llm-providers/{id} ────────────────────────────────────────────────

@router.patch("/{config_id}", response_model=LLMProviderConfigOut, summary="Configure a model")
def update_provider(
    config_id: str,
    body: LLMProviderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> LLMProviderConfigOut:
    config = llm_config_service.get_config_or_404(db, config_id)
    updated = llm_config_service.update_config(db, config, **body.model_dump(exclude_unset=True))
    _audit(db, "llm_provider_configured", current_user, f"name={updated.name} fields={list(body.model_dump(exclude_unset=True).keys())}")
    return _to_out(updated)


# ── POST /llm-providers/{id}/activate ────────────────────────────────────────

@router.post("/{config_id}/activate", response_model=LLMProviderConfigOut, summary="Activate a model")
def activate_provider(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> LLMProviderConfigOut:
    config = llm_config_service.get_config_or_404(db, config_id)
    llm_config_service.activate_config(db, config)
    _audit(db, "llm_provider_activated", current_user, f"name={config.name}")
    return _to_out(config)


# ── POST /llm-providers/{id}/deactivate ──────────────────────────────────────

@router.post("/{config_id}/deactivate", response_model=LLMProviderConfigOut, summary="Deactivate a model")
def deactivate_provider(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> LLMProviderConfigOut:
    config = llm_config_service.get_config_or_404(db, config_id)
    llm_config_service.deactivate_config(db, config)
    _audit(db, "llm_provider_deactivated", current_user, f"name={config.name}")
    return _to_out(config)


# ── POST /llm-providers/{id}/switch-active ───────────────────────────────────

@router.post("/{config_id}/switch-active", response_model=SwitchActiveResponse, summary="Switch the active model")
def switch_active_provider(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> SwitchActiveResponse:
    config = llm_config_service.get_config_or_404(db, config_id)
    llm_config_service.switch_active(db, config)
    _audit(db, "llm_switched", current_user, f"name={config.name} provider={config.provider} model={config.model}")
    return SwitchActiveResponse(id=str(config.id), name=config.name, provider=config.provider, model=config.model)


# ── POST /llm-providers/{id}/test-connection ─────────────────────────────────

@router.post("/{config_id}/test-connection", response_model=TestConnectionResponse, summary="Test model connection")
async def test_provider_connection(
    config_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LLM_CONFIGURE)),
) -> TestConnectionResponse:
    config = llm_config_service.get_config_or_404(db, config_id)
    result = await llm_config_service.test_connection(config)
    return TestConnectionResponse(
        success=result.success, message=result.message, latency_ms=result.latency_ms, model_used=result.model_used,
    )
