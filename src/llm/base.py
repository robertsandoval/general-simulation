"""Abstract base (Protocol) for LLM client implementations.

All concrete clients (OpenAIClient, LlamaStackClient, FakeLLMClient) must
satisfy this interface.  Code outside src/llm/ should only type-hint against
this Protocol, never against concrete implementations.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.llm.types import Chunk, GenerateResult, Message


@runtime_checkable
class LLMClientBase(Protocol):
    """Thin surface the app uses for all LLM, embedding, and RAG work."""

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> GenerateResult:
        """Chat completion (with optional tool schemas).

        ``tools`` uses the OpenAI function-calling JSON schema shape:
        ``[{"type": "function", "function": {"name": ..., "parameters": ...}}]``.
        """
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input text."""
        ...

    async def ingest_documents(
        self,
        documents: list[dict[str, Any]],
        vector_db_id: str,
    ) -> None:
        """Embed and store documents in the named vector collection.

        Each document dict must have at least:
          - ``"id"`` (str): unique document identifier
          - ``"content"`` (str): text to embed and store
        Optional key:
          - ``"metadata"`` (dict): arbitrary key-value pairs stored with the chunk
        """
        ...

    async def vector_search(
        self,
        query: str,
        vector_db_id: str,
        top_k: int = 5,
    ) -> list[Chunk]:
        """Semantic search over the named vector collection.

        Returns up to ``top_k`` chunks ranked by relevance.
        """
        ...

    async def ensure_vector_db(
        self,
        vector_db_id: str,
        provider_id: str | None = None,
    ) -> None:
        """Create the vector collection if it does not already exist.

        Idempotent — safe to call before every ingest or search.
        """
        ...

    async def unregister_vector_db(self, vector_db_id: str) -> None:
        """Drop a vector collection and all its stored embeddings.

        Used by ``remove_scenario()`` to fully clean up a scenario's vector data.
        Safe to call on a collection that does not exist.
        """
        ...
