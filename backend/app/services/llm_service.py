"""
LLM Service
-----------
Provides a unified LangChain LLM/chat-model interface that switches between
Ollama (local), OpenAI, and Groq based on the LLM_PROVIDER env variable.
"""
from __future__ import annotations

from functools import lru_cache
from langchain_core.language_models import BaseChatModel
from app.core.config import settings


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Return a cached LangChain chat model based on the configured provider."""
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.7,
        )

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0.7,
        )

    # Default: Ollama (local)
    from langchain_community.chat_models import ChatOllama
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0.7,
    )


async def generate_response(prompt: str) -> str:
    """Simple wrapper: send a prompt and return the string response."""
    llm = get_llm()
    response = await llm.ainvoke(prompt)
    return response.content
