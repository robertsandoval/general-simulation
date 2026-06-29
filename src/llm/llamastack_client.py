"""Llama Stack client — wraps the llama-stack-client SDK.

This backend is dormant by default.  Activate it by setting:
    LLM_BACKEND=llamastack

and ensuring the llama-stack-client package is installed:
    pip install llama-stack-client

The Llama Stack server exposes an OpenAI-compatible /v1 endpoint, so you can
also keep LLM_BACKEND=openai and simply point LLM_BASE_URL at the Llama Stack
server — this avoids the dependency entirely.  Use LLM_BACKEND=llamastack only
if you need Llama Stack-specific vector_io / RAG APIs.
"""
from __future__ import annotations

import logging
from typing import Any

from llama_stack_client import AsyncLlamaStackClient
from llama_stack_client.types import (
    ChatCompletionResponse,
    EmbeddingsResponse,
    QueryChunksResponse,
)

from src.core.config import Settings
from src.llm.types import Chunk, GenerateResult, Message, ToolCall

logger = logging.getLogger(__name__)

_DOC_ID_META_KEY = "_sim_document_id"


class LlamaStackClient:
    """Thin async wrapper around the llama-stack-client SDK."""

    def __init__(self, settings: Settings, pool: Any = None) -> None:
        self._settings = settings
        self._sdk = AsyncLlamaStackClient(base_url=settings.llm_base_url)
        self._registered_dbs: set[str] = set()

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> GenerateResult:
        sdk_messages = [{"role": m.role, "content": m.content} for m in messages]
        response: ChatCompletionResponse = (
            await self._sdk.inference.chat_completion(
                model_id=self._settings.generation_model_id,
                messages=sdk_messages,  # type: ignore[arg-type]
                tools=tools or [],  # type: ignore[arg-type]
            )
        )
        msg = response.completion_message
        content: str | None = msg.content if isinstance(msg.content, str) else None
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    call_id=tc.call_id,
                    tool_name=str(tc.tool_name),
                    arguments=tc.arguments if isinstance(tc.arguments, dict) else {},
                )
                for tc in msg.tool_calls
            ]
        return GenerateResult(
            content=content,
            tool_calls=tool_calls,
            stop_reason=msg.stop_reason,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response: EmbeddingsResponse = (
            await self._sdk.inference.embeddings(
                model_id=self._settings.embedding_model_id,
                contents=texts,  # type: ignore[arg-type]
            )
        )
        return response.embeddings

    async def ingest_documents(
        self,
        documents: list[dict[str, Any]],
        vector_db_id: str,
    ) -> None:
        await self.ensure_vector_db(vector_db_id)
        chunks = [
            {
                "content": doc["content"],
                "metadata": {
                    _DOC_ID_META_KEY: doc["id"],
                    **doc.get("metadata", {}),
                },
            }
            for doc in documents
        ]
        await self._sdk.vector_io.insert(
            vector_db_id=vector_db_id,
            chunks=chunks,  # type: ignore[arg-type]
        )

    async def vector_search(
        self,
        query: str,
        vector_db_id: str,
        top_k: int = 5,
    ) -> list[Chunk]:
        response: QueryChunksResponse = await self._sdk.vector_io.query(
            vector_db_id=vector_db_id,
            query=query,  # type: ignore[arg-type]
            params={"max_chunks": top_k},
        )
        results: list[Chunk] = []
        for chunk, score in zip(response.chunks, response.scores):
            meta: dict[str, Any] = dict(chunk.metadata)
            doc_id = str(meta.pop(_DOC_ID_META_KEY, "unknown"))
            content = chunk.content if isinstance(chunk.content, str) else ""
            results.append(
                Chunk(document_id=doc_id, content=content, score=score, metadata=meta)
            )
        return results

    async def ensure_vector_db(
        self,
        vector_db_id: str,
        provider_id: str | None = None,
    ) -> None:
        if vector_db_id in self._registered_dbs:
            return
        try:
            await self._sdk.vector_dbs.register(
                vector_db_id=vector_db_id,
                embedding_model=self._settings.embedding_model_id,
                embedding_dimension=self._settings.embedding_dimension,
                provider_id=provider_id or "pgvector-store",
            )
        except Exception as exc:
            logger.debug(
                "vector_dbs.register for '%s' raised %s (may already exist)",
                vector_db_id,
                exc,
            )
        self._registered_dbs.add(vector_db_id)

    async def unregister_vector_db(self, vector_db_id: str) -> None:
        try:
            await self._sdk.vector_dbs.unregister(vector_db_id=vector_db_id)
        except Exception as exc:
            logger.debug(
                "vector_dbs.unregister for '%s' raised %s (may not exist)",
                vector_db_id,
                exc,
            )
        self._registered_dbs.discard(vector_db_id)
