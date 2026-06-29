"""LLM client factory.

Returns the correct LLMClientBase implementation based on Settings.llm_backend:

    openai      (default) OpenAI-compatible endpoint + pgvector directly
    llamastack            Llama Stack SDK (requires llama-stack-client installed)
    fake                  In-memory stub for tests / GPU-free dev

Usage:
    from src.llm.factory import get_llm_client
    client = get_llm_client(settings, pool)

The ``pool`` parameter is required for the openai backend (vector ops talk to
pgvector directly).  It is ignored by the llamastack and fake backends.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.config import Settings
from src.llm.base import LLMClientBase

if TYPE_CHECKING:
    import asyncpg


def get_llm_client(
    settings: Settings | None = None,
    pool: Any = None,
) -> LLMClientBase:
    """Return an LLMClientBase for the configured backend."""
    if settings is None:
        settings = Settings()

    backend = settings.llm_backend.lower()

    if backend == "fake":
        from src.llm.fake import FakeLLMClient
        return FakeLLMClient(settings=settings, pool=pool)  # type: ignore[return-value]

    if backend == "llamastack":
        from src.llm.llamastack_client import LlamaStackClient
        return LlamaStackClient(settings=settings, pool=pool)  # type: ignore[return-value]

    # Default: openai-compatible endpoint
    from src.llm.openai_client import OpenAIClient
    return OpenAIClient(settings=settings, pool=pool)  # type: ignore[return-value]
