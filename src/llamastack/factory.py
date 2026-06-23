"""Client factory — returns the real or fake client based on Settings.

Usage (anywhere in the app):
    from src.llamastack.factory import get_llama_stack_client
    client = get_llama_stack_client(settings)

The fake client is selected when ``USE_FAKE_LLAMA_STACK=true`` (or when
running under pytest with a test settings object that sets the flag).
"""
from __future__ import annotations

from src.core.config import Settings
from src.llamastack.base import LlamaStackClientBase
from src.llamastack.client import LlamaStackClient
from src.llamastack.fake import FakeLlamaStackClient


def get_llama_stack_client(
    settings: Settings | None = None,
) -> LlamaStackClientBase:
    """Return an appropriate LlamaStackClient based on the active settings.

    Falls back to ``Settings()`` (reads from env / .env) when *settings* is
    not provided.
    """
    if settings is None:
        settings = Settings()

    if settings.use_fake_llama_stack:
        return FakeLlamaStackClient(settings=settings)  # type: ignore[return-value]
    return LlamaStackClient(settings=settings)  # type: ignore[return-value]
