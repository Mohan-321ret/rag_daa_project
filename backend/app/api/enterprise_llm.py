"""
Enterprise LLM API Router  –  Phase 10 Module 8
------------------------------------------------------
Endpoint: GET /api/v1/llm/models

Lists the supported model aliases (Llama 3 / Gemma / Mistral / Qwen) and
whether each is actually available on the local Ollama daemon, so a
caller can pick a model — via the `model` field on POST /api/v1/rag/query
— that's known to work before spending a request on it.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import Permission
from app.db.database import get_db
from app.models.user import User
from app.schemas.enterprise_llm import ModelInfo, ModelsResponse
from app.services.auth_service import require_permission
from app.services.llm_service import get_active_config, is_ollama_model_available, list_ollama_models, resolve_ollama_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["Enterprise LLM (Module 8)"])


@router.get(
    "/models",
    response_model=ModelsResponse,
    status_code=status.HTTP_200_OK,
    summary="List supported LLM models and their local availability",
    description=(
        "Reports the alias registry (llama3/gemma/mistral/qwen → Ollama tag) "
        "and, for the Ollama provider, which of those are actually pulled "
        "locally — plus the raw list of everything Ollama has installed."
    ),
)
def list_models(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.LLM_VIEW)),
) -> ModelsResponse:
    # Sourced from the centralized LLM Provider Manager (Admin Panel: LLM and
    # Model Switching) so this reflects whatever an admin last activated —
    # not a stale .env snapshot — with no duplicated provider-selection logic.
    cfg = get_active_config(db)
    registry = settings.llm_model_registry_map
    is_ollama = cfg.provider == "ollama"

    installed = list_ollama_models() if is_ollama else []
    models = [
        ModelInfo(
            alias=alias,
            tag=tag,
            available=is_ollama_model_available(tag, installed) if is_ollama else True,
        )
        for alias, tag in registry.items()
    ]

    return ModelsResponse(
        provider=cfg.provider,
        default_alias=settings.llm_default_model_alias if is_ollama else cfg.model,
        default_tag=resolve_ollama_model(cfg.model) if is_ollama else cfg.model,
        models=models,
        installed_raw=installed,
    )
