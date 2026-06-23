"""Tests for the Llama Stack client layer.

All tests use FakeLlamaStackClient — no live Llama Stack server or GPU needed.
The "done when" checks from the build plan:
  - embed() returns vectors of the configured dimension
  - vector_search() returns hits from documents ingested via ingest_documents()
  - generate() round-trips a tool-call request/response shape
"""
from __future__ import annotations

import math

import pytest

from src.core.config import Settings
from src.llamastack.base import LlamaStackClientBase
from src.llamastack.fake import FakeLlamaStackClient, _cosine, _hash_embed
from src.llamastack.factory import get_llama_stack_client
from src.llamastack.types import Message, ToolCall


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _fake_settings(**overrides) -> Settings:
    base = dict(
        postgres_dsn="postgresql://mock:mock@localhost/mock",
        llama_stack_base_url="http://localhost:8321",
        use_fake_llama_stack=True,
        embedding_dimension=16,  # small for fast tests
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def fake_client() -> FakeLlamaStackClient:
    return FakeLlamaStackClient(settings=_fake_settings())


# ── Factory ───────────────────────────────────────────────────────────────────


def test_factory_returns_fake_when_flag_set():
    client = get_llama_stack_client(_fake_settings(use_fake_llama_stack=True))
    assert isinstance(client, FakeLlamaStackClient)


def test_factory_satisfies_protocol():
    client = get_llama_stack_client(_fake_settings(use_fake_llama_stack=True))
    assert isinstance(client, LlamaStackClientBase)


# ── embed() ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embed_returns_correct_number_of_vectors(fake_client):
    texts = ["hello world", "second sentence", "third one"]
    vecs = await fake_client.embed(texts)
    assert len(vecs) == len(texts)


@pytest.mark.asyncio
async def test_embed_returns_configured_dimension(fake_client):
    vecs = await fake_client.embed(["any text"])
    assert len(vecs[0]) == fake_client._settings.embedding_dimension


@pytest.mark.asyncio
async def test_embed_vectors_are_unit_length(fake_client):
    vecs = await fake_client.embed(["normalised?"])
    mag = math.sqrt(sum(x * x for x in vecs[0]))
    assert abs(mag - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_embed_is_deterministic(fake_client):
    v1 = await fake_client.embed(["stable"])
    v2 = await fake_client.embed(["stable"])
    assert v1 == v2


@pytest.mark.asyncio
async def test_embed_distinct_texts_give_distinct_vectors(fake_client):
    vecs = await fake_client.embed(["apple", "orange"])
    assert vecs[0] != vecs[1]


# ── ingest_documents + vector_search ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_vector_search_returns_ingested_documents(fake_client):
    docs = [
        {"id": "doc-1", "content": "The sky is blue"},
        {"id": "doc-2", "content": "Grass is green"},
        {"id": "doc-3", "content": "Water is wet"},
    ]
    await fake_client.ingest_documents(docs, vector_db_id="test_db")
    results = await fake_client.vector_search("blue sky", vector_db_id="test_db")

    assert len(results) > 0
    returned_ids = {r.document_id for r in results}
    # At least one document should be returned
    assert returned_ids.issubset({"doc-1", "doc-2", "doc-3"})


@pytest.mark.asyncio
async def test_vector_search_top_k_is_respected(fake_client):
    docs = [{"id": f"d{i}", "content": f"document {i}"} for i in range(10)]
    await fake_client.ingest_documents(docs, vector_db_id="topk_db")
    results = await fake_client.vector_search("document", "topk_db", top_k=3)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_vector_search_scores_descending(fake_client):
    docs = [{"id": f"doc{i}", "content": f"item {i}"} for i in range(5)]
    await fake_client.ingest_documents(docs, vector_db_id="score_db")
    results = await fake_client.vector_search("item", "score_db", top_k=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_vector_search_empty_store_returns_empty(fake_client):
    results = await fake_client.vector_search("anything", "no_such_db")
    assert results == []


@pytest.mark.asyncio
async def test_ingest_preserves_metadata(fake_client):
    docs = [{"id": "m1", "content": "text", "metadata": {"source": "test", "year": 2026}}]
    await fake_client.ingest_documents(docs, "meta_db")
    results = await fake_client.vector_search("text", "meta_db")
    assert results[0].metadata.get("source") == "test"
    assert results[0].metadata.get("year") == 2026


@pytest.mark.asyncio
async def test_most_similar_document_ranked_first(fake_client):
    # Ingest two docs; query for the content of doc-A verbatim — it should rank first.
    docs = [
        {"id": "doc-A", "content": "unique phrase alpha beta gamma"},
        {"id": "doc-B", "content": "completely different content here"},
    ]
    await fake_client.ingest_documents(docs, "rank_db")
    results = await fake_client.vector_search(
        "unique phrase alpha beta gamma", "rank_db"
    )
    assert results[0].document_id == "doc-A"


# ── generate() ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_returns_content_when_no_tools(fake_client):
    result = await fake_client.generate(
        messages=[Message(role="user", content="Hello")]
    )
    assert result.content is not None
    assert isinstance(result.content, str)
    assert result.tool_calls == []
    assert result.stop_reason == "end_of_turn"


@pytest.mark.asyncio
async def test_generate_round_trips_tool_call_shape():
    """When canned_tool_calls is set and tools schemas are provided,
    generate() returns tool_calls and no plain content — matching the
    end_of_message stop_reason that real models use for tool invocations.
    """
    canned = [
        ToolCall(
            call_id="call-1",
            tool_name="get_entity_state",
            arguments={"entity_id": "E42", "scenario_id": "s1"},
        )
    ]
    client = FakeLlamaStackClient(
        settings=_fake_settings(),
        canned_tool_calls=canned,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_entity_state",
                "description": "Fetch live state for an entity",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "scenario_id": {"type": "string"},
                    },
                    "required": ["entity_id", "scenario_id"],
                },
            },
        }
    ]
    result = await client.generate(
        messages=[Message(role="user", content="What is the state of E42?")],
        tools=tools,
    )

    assert result.content is None
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.call_id == "call-1"
    assert tc.tool_name == "get_entity_state"
    assert tc.arguments["entity_id"] == "E42"
    assert result.stop_reason == "end_of_message"


@pytest.mark.asyncio
async def test_generate_content_when_tools_provided_but_no_canned_calls(fake_client):
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]
    result = await fake_client.generate(
        messages=[Message(role="user", content="no tool needed")],
        tools=tools,
    )
    assert result.content is not None
    assert result.tool_calls == []


# ── ensure_vector_db ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_vector_db_is_idempotent(fake_client):
    await fake_client.ensure_vector_db("idem_db")
    await fake_client.ensure_vector_db("idem_db")
    assert "idem_db" in fake_client._store


# ── _hash_embed helpers ───────────────────────────────────────────────────────


def test_hash_embed_dimension():
    assert len(_hash_embed("test", 32)) == 32


def test_hash_embed_unit_length():
    vec = _hash_embed("unit", 64)
    mag = math.sqrt(sum(x * x for x in vec))
    assert abs(mag - 1.0) < 1e-6


def test_cosine_identical_vectors():
    vec = _hash_embed("same", 16)
    assert abs(_cosine(vec, vec) - 1.0) < 1e-6
