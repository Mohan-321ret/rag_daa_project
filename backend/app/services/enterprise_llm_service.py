"""
Enterprise LLM Engine  –  Phase 10 Module 8 (Orchestrator)
------------------------------------------------------------------
Wires the final leg of the RAG pipeline:

  Prompt = System Prompt + Retrieved Context + User Question   [Phase 9 – prompt_builder]
       ↓
  LLM  (Llama 3 / Gemma / Mistral / Qwen via Ollama, or OpenAI/Groq)  [llm_service]
       ↓
  Grounded Answer   – verified against the supplied context             [citation_service]
       ↓
  Citations         – [DOC_xxxx] markers resolved back to source chunks [citation_service]

Entry point: generate_answer(prompt, context_chunks, model=None)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.services.citation_service import GroundingResult, extract_citations
from app.services.llm_service import (
    get_active_config,
    get_llm,
    is_ollama_model_available,
    list_ollama_models,
    resolve_ollama_model,
)
from app.services.prompt_builder import BuiltPrompt

logger = logging.getLogger(__name__)


@dataclass
class GeneratedAnswer:
    answer: str
    model_used: str
    provider: str
    model_available: Optional[bool]   # None when not checkable (non-Ollama provider)
    grounding: GroundingResult


def _clean_reasoning_tags(text: str) -> str:
    """Strip out internal reasoning blocks like <think>...</think> produced by reasoning models (Qwen, DeepSeek)."""
    import re
    if not text:
        return ""
    if "<think>" in text:
        cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL).strip()
        if cleaned:
            return cleaned
        # If the model placed its entire answer inside <think>...</think> (or was cut off), return the inner text
        inside = re.sub(r"</?think>", "", text, flags=re.DOTALL).strip()
        if inside:
            return inside
    return text.strip()


async def generate_answer(
    prompt: BuiltPrompt,
    context_chunks: List[dict],
    model: Optional[str] = None,
) -> GeneratedAnswer:
    """
    Generate a grounded, citable answer from an already-built prompt.

    Args:
        prompt:          Output of Phase 9's prompt_builder.build_prompt().
        context_chunks:  The exact chunks Phase 9 put into the prompt's
                         context — used to validate citations/grounding.
        model:            Optional model alias/tag override ("llama3",
                         "gemma", "mistral", "qwen", or a raw Ollama tag).
                         Ignored for the OpenAI/Groq providers.

    Returns:
        GeneratedAnswer with the raw answer text, which model actually
        served it, and the grounding/citation verdict.

    Raises:
        RuntimeError: If the LLM call itself fails.
    """
    cfg = get_active_config()
    provider = cfg.provider
    resolved_model: str
    model_available: Optional[bool] = None

    if provider in ("openai", "groq"):
        resolved_model = cfg.model
    else:
        resolved_model = resolve_ollama_model(model or cfg.model)
        installed = list_ollama_models()
        model_available = is_ollama_model_available(resolved_model, installed)
        if not model_available:
            logger.warning(
                "[EnterpriseLLM] Requested model '%s' not found on the local Ollama "
                "daemon (installed: %s) — attempting anyway; it may auto-pull or fail.",
                resolved_model, installed or "(none / daemon unreachable)",
            )

    try:
        llm = get_llm(model)
        response = await llm.ainvoke(prompt.full_prompt)
        answer_text: str = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        logger.warning(
            "[EnterpriseLLM] Primary LLM call failed (provider=%s model=%s): %s — attempting fallback to Ollama...",
            provider, resolved_model, exc
        )
        if provider != "ollama":
            try:
                from app.core.config import settings
                from app.services.llm_service import build_llm
                fallback_model = resolve_ollama_model("llama3")
                fallback_llm = build_llm(
                    "ollama", fallback_model, settings.ollama_base_url, None,
                    cfg.temperature, cfg.max_tokens, cfg.context_window
                )
                response = await fallback_llm.ainvoke(prompt.full_prompt)
                answer_text = response.content if hasattr(response, "content") else str(response)
                resolved_model = f"ollama/{fallback_model} (fallback from {provider})"
                provider = "ollama"
            except Exception as fb_exc:
                logger.error("[EnterpriseLLM] Fallback to Ollama also failed: %s", fb_exc)
                raise RuntimeError(f"LLM generation failed on primary ({cfg.provider}) and fallback (ollama): {exc}") from exc
        else:
            raise RuntimeError(f"LLM generation failed: {exc}") from exc

    answer_text = _clean_reasoning_tags(answer_text)
    grounding = extract_citations(answer_text, context_chunks)

    logger.info(
        "[EnterpriseLLM] ✅ provider=%s model=%s grounded=%s citations=%d declined=%s",
        provider, resolved_model, grounding.is_grounded,
        len(grounding.citations), grounding.declined,
    )

    return GeneratedAnswer(
        answer=answer_text,
        model_used=resolved_model,
        provider=provider,
        model_available=model_available,
        grounding=grounding,
    )

