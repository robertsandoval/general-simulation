"""Abstract base (Protocol) for the Llama Stack client surface.

Both LlamaStackClient (real) and FakeLlamaStackClient must satisfy this
interface.  Code outside src/llamastack should only type-hint against this
Protocol, never against the concrete implementations.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.llamastack.types import Chunk, GenerateResult, Message


@runtime_checkable
class LlamaStackClientBase(Protocol):
    """Thin surface the app uses for all LLM, embedding, and RAG work.

    Inference and vector/RAG go through the Llama Stack server — never
    directly to vLLM or pgvector SQL.
    """

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> GenerateResult:
        """Chat completion (with optional tool schemas).

        ``tools`` uses the OpenAI function-calling JSON schema shape:
        ``[{"type": "function", "function": {"name": ..., "parameters": ...}}]``.
        The model may respond with tool_calls instead of (or in addition to)
        plain content.
        """
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Returns one vector per input text.  Dimension matches the embedding
        model registered in Llama Stack (see EMBEDDING_DIMENSION in settings).
        """
        ...

    async def ingest_documents(
        self,
        documents: list[dict[str, Any]],
        vector_db_id: str,
    ) -> None:
        """Ingest documents into a Llama Stack vector DB.

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
        """Semantic search over a Llama Stack vector DB.

        Returns up to ``top_k`` chunks ranked by relevance.
        """
        ...

    async def ensure_vector_db(
        self,
        vector_db_id: str,
        provider_id: str | None = None,
    ) -> None:
        """Register the vector DB if it does not already exist.

        Idempotent — safe to call before every ingest or search.  The
        embedding model and dimension come from Settings.
        """
        ...

    async def unregister_vector_db(self, vector_db_id: str) -> None:
        """Unregister a vector DB and remove all its stored embeddings.

        Used by ``remove_scenario()`` to fully clean up a scenario's vector
        data.  Safe to call on a DB that does not exist.
        """
        ...
