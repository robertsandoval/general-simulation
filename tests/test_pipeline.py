"""Phase 7 — Three-stage reasoning pipeline tests.

Coverage:
  - Stage 1 (stage1.py): structural AGE traversal
  - Stage 2 (stage2.py): live state read + solver
  - Stage 3 (stage3.py): vector retrieval + LLM synthesis
  - Pipeline orchestrator (pipeline.py): end-to-end wiring
  - POST /query endpoint (api/query.py): full HTTP round-trip

No live DB or GPU required:
  - asyncpg pool/connection are mocked (MagicMock / AsyncMock)
  - FakeLlamaStackClient provides in-memory vector search and generation
  - StubSolver provides deterministic quantitative output
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.deps import get_llm_client, get_pool, get_solver
from src.core.config import Settings
from src.core.solver import AffectedSubgraph, EntityState
from src.llamastack.fake import FakeLlamaStackClient
from src.reasoning.pipeline import run_pipeline
from src.reasoning.stage1 import run_stage1
from src.reasoning.stage2 import run_stage2
from src.reasoning.stage3 import run_stage3
from src.reasoning.types import QueryRequest
from src.solver.stub import StubSolver


# ── Test constants ─────────────────────────────────────────────────────────────

SCENARIO_ID = "test_scenario_phase7"
ENTITY_A = "entity-A"
ENTITY_B = "entity-B"
ENTITY_C = "entity-C"
ALL_ENTITIES = [ENTITY_A, ENTITY_B, ENTITY_C]
QUESTION = "What is the expected impact on downstream entities?"

# Edges: A →DEPENDS_ON→ B →FEEDS→ C  (chain length 2)
EDGES = [
    (ENTITY_A, ENTITY_B, "DEPENDS_ON"),
    (ENTITY_B, ENTITY_C, "FEEDS"),
]


# ── Mock helpers ───────────────────────────────────────────────────────────────


def _settings() -> Settings:
    return Settings(
        postgres_dsn="postgresql://mock:mock@localhost/mock",
        llama_stack_base_url="http://localhost:8321",
        use_fake_llama_stack=True,
        embedding_dimension=16,
    )


def _fake_client() -> FakeLlamaStackClient:
    return FakeLlamaStackClient(settings=_settings())


def _conn() -> AsyncMock:
    """Mock asyncpg connection with a no-op fetch by default."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    return conn


def _pool(conn: AsyncMock) -> MagicMock:
    """Mock asyncpg pool that yields *conn* from every acquire()."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# Row factories for mocked asyncpg results

def _entity_id_rows(*entity_ids: str) -> list[dict[str, Any]]:
    """AGE result rows for RETURN n.id queries (agtype-encoded strings)."""
    return [{"result": f'"{eid}"'} for eid in entity_ids]


def _edge_rows(*edges: tuple[str, str, str]) -> list[dict[str, Any]]:
    """AGE result rows for edge queries returning {from_id, edge_type, to_id}."""
    return [
        {"result": json.dumps({"from_id": f, "edge_type": et, "to_id": t})}
        for f, t, et in edges
    ]


def _live_state_rows(*specs: tuple[str, str]) -> list[dict[str, Any]]:
    """PostGIS live state rows for (entity_id, status) pairs."""
    return [
        {
            "id": eid,
            "type": "moving_entity",
            "entity_attrs": {},
            "status": status,
            "state_attrs": {},
        }
        for eid, status in specs
    ]


def _standard_fetch_side_effect() -> list[list[dict]]:
    """Three sequential conn.fetch() responses for Stage 1a, 1b, and Stage 2."""
    return [
        # Stage 1a — affected entity IDs from AFFECTED_BY AGE query
        _entity_id_rows(*ALL_ENTITIES),
        # Stage 1b — dependency edges within the subgraph
        _edge_rows(*EDGES),
        # Stage 2 — live state from PostGIS
        _live_state_rows(
            (ENTITY_A, "operational"),
            (ENTITY_B, "operational"),
            (ENTITY_C, "degraded"),
        ),
    ]


# ── Stage 1 unit tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage1_returns_empty_subgraph_when_no_events():
    conn = _conn()
    conn.fetch.return_value = []  # no entities found
    pool = _pool(conn)

    subgraph = await run_stage1(SCENARIO_ID, pool)

    assert subgraph.affected_entity_ids == []
    assert subgraph.dependency_edges == []
    assert subgraph.scenario_id == SCENARIO_ID
    assert conn.fetch.call_count == 1  # only the entities query (no edge query)


@pytest.mark.asyncio
async def test_stage1_returns_affected_entities_and_edges():
    conn = _conn()
    conn.fetch.side_effect = [
        _entity_id_rows(*ALL_ENTITIES),
        _edge_rows(*EDGES),
    ]
    pool = _pool(conn)

    subgraph = await run_stage1(SCENARIO_ID, pool)

    assert set(subgraph.affected_entity_ids) == set(ALL_ENTITIES)
    assert len(subgraph.dependency_edges) == 2
    # Verify edge tuple order: (from_id, to_id, edge_type)
    edge_set = {(f, t, et) for f, t, et in subgraph.dependency_edges}
    assert (ENTITY_A, ENTITY_B, "DEPENDS_ON") in edge_set
    assert (ENTITY_B, ENTITY_C, "FEEDS") in edge_set
    assert subgraph.scenario_id == SCENARIO_ID


@pytest.mark.asyncio
async def test_stage1_skips_malformed_edge_rows():
    conn = _conn()
    conn.fetch.side_effect = [
        _entity_id_rows(ENTITY_A, ENTITY_B),
        # One valid edge, one bad row (missing keys)
        [
            {"result": json.dumps({"from_id": ENTITY_A, "edge_type": "DEPENDS_ON", "to_id": ENTITY_B})},
            {"result": "null"},  # missing keys after parse → skipped
        ],
    ]
    pool = _pool(conn)

    subgraph = await run_stage1(SCENARIO_ID, pool)

    assert len(subgraph.dependency_edges) == 1


# ── Stage 2 unit tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage2_returns_live_state_and_solver_result():
    conn = _conn()
    conn.fetch.return_value = _live_state_rows(
        (ENTITY_A, "operational"), (ENTITY_B, "operational")
    )
    pool = _pool(conn)

    subgraph = AffectedSubgraph(
        event_id="scenario:s1",
        scenario_id="s1",
        affected_entity_ids=[ENTITY_A, ENTITY_B],
        dependency_edges=[(ENTITY_A, ENTITY_B, "DEPENDS_ON")],
    )

    live_state, result = await run_stage2(subgraph, pool, StubSolver())

    assert ENTITY_A in live_state
    assert ENTITY_B in live_state
    assert live_state[ENTITY_A].status == "operational"
    assert result.affected_count == 2
    assert result.max_chain_length >= 1


@pytest.mark.asyncio
async def test_stage2_seeds_unknown_state_for_missing_entities():
    """Entities not in the DB should get a default 'unknown' state."""
    conn = _conn()
    # DB returns only ENTITY_A; ENTITY_B is missing
    conn.fetch.return_value = _live_state_rows((ENTITY_A, "operational"))
    pool = _pool(conn)

    subgraph = AffectedSubgraph(
        event_id="s",
        scenario_id="s",
        affected_entity_ids=[ENTITY_A, ENTITY_B],
    )

    live_state, _ = await run_stage2(subgraph, pool, StubSolver())

    assert live_state[ENTITY_A].status == "operational"
    assert live_state[ENTITY_B].status == "unknown"


@pytest.mark.asyncio
async def test_stage2_empty_entity_list():
    conn = _conn()
    pool = _pool(conn)

    subgraph = AffectedSubgraph(
        event_id="s", scenario_id="s", affected_entity_ids=[]
    )

    live_state, result = await run_stage2(subgraph, pool, StubSolver())

    assert live_state == {}
    assert result.affected_count == 0
    conn.fetch.assert_not_called()


# ── Stage 3 unit tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage3_returns_non_empty_answer():
    client = _fake_client()
    vdb_id = f"sim_events_{SCENARIO_ID}"
    await client.ensure_vector_db(vdb_id)
    await client.ingest_documents(
        [{"id": "doc-1", "content": "Substation A tripped offline."}],
        vdb_id,
    )

    subgraph = AffectedSubgraph(
        event_id="scenario:s",
        scenario_id=SCENARIO_ID,
        affected_entity_ids=[ENTITY_A],
    )
    solver_result = StubSolver().solve(subgraph, {})

    answer = await run_stage3(
        question=QUESTION,
        subgraph=subgraph,
        solver_result=solver_result,
        llm_client=client,
    )

    assert isinstance(answer, str)
    assert len(answer) > 0


@pytest.mark.asyncio
async def test_stage3_fallback_when_no_vector_context():
    """Stage 3 must not crash when the vector DB has no matching chunks."""
    client = _fake_client()
    # Do NOT ingest any documents; vector_search returns []

    subgraph = AffectedSubgraph(
        event_id="s", scenario_id=SCENARIO_ID, affected_entity_ids=[ENTITY_A]
    )
    solver_result = StubSolver().solve(subgraph, {})

    answer = await run_stage3(
        question=QUESTION,
        subgraph=subgraph,
        solver_result=solver_result,
        llm_client=client,
    )

    assert isinstance(answer, str)
    assert len(answer) > 0


# ── Pipeline orchestrator unit tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_run_returns_structured_response():
    conn = _conn()
    conn.fetch.side_effect = _standard_fetch_side_effect()
    pool = _pool(conn)

    client = _fake_client()
    vdb_id = f"sim_events_{SCENARIO_ID}"
    await client.ensure_vector_db(vdb_id)
    await client.ingest_documents(
        [{"id": "evt-pip-1", "content": "Major fault on substation A."}],
        vdb_id,
    )

    request = QueryRequest(question=QUESTION, scenario_id=SCENARIO_ID)
    response = await run_pipeline(request, pool, client, StubSolver())

    assert response.question == QUESTION
    assert response.scenario_id == SCENARIO_ID
    assert set(response.affected_entities) == set(ALL_ENTITIES)
    assert response.solver.affected_count == 3
    assert response.solver.max_chain_length == 2
    assert response.solver.impact_score > 0
    assert len(response.answer) > 0
    assert len(response.solver.response_options) > 0


@pytest.mark.asyncio
async def test_pipeline_no_events_returns_empty_affected_set():
    """Pipeline must succeed gracefully when no events are injected."""
    conn = _conn()
    conn.fetch.side_effect = [
        [],                    # Stage 1a: no entities
        _live_state_rows(),    # Stage 2: no rows either
    ]
    pool = _pool(conn)

    client = _fake_client()
    request = QueryRequest(question=QUESTION, scenario_id="empty_scenario")
    response = await run_pipeline(request, pool, client, StubSolver())

    assert response.affected_entities == []
    assert response.solver.affected_count == 0
    assert isinstance(response.answer, str)


# ── POST /query end-to-end HTTP tests ─────────────────────────────────────────


@pytest.fixture()
def _query_app_overrides():
    """Set up dependency overrides for POST /query tests; tear down after."""
    conn = _conn()
    conn.fetch.side_effect = _standard_fetch_side_effect()
    pool = _pool(conn)

    client = _fake_client()

    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[get_llm_client] = lambda: client
    app.dependency_overrides[get_solver] = lambda: StubSolver()

    yield conn, client

    app.dependency_overrides.pop(get_pool, None)
    app.dependency_overrides.pop(get_llm_client, None)
    app.dependency_overrides.pop(get_solver, None)


@pytest.mark.asyncio
async def test_post_query_end_to_end(_query_app_overrides):
    """
    Full HTTP round-trip: POST /query → pipeline → structured JSON response.

    Verifies:
      - HTTP 200 and correct response shape
      - Stage-1 affected entities match mocked AGE traversal output
      - Stage-2 solver ran (affected_count and chain length present)
      - Stage-3 synthesis produced a non-empty answer string
    """
    conn, client = _query_app_overrides

    # Pre-ingest an event description into the fake vector store so Stage 3
    # has context to retrieve.
    vdb_id = f"sim_events_{SCENARIO_ID}"
    await client.ensure_vector_db(vdb_id)
    await client.ingest_documents(
        [
            {
                "id": "evt-e2e-1",
                "content": "Substation A tripped offline; cascading fault reaches B and C.",
            }
        ],
        vdb_id,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            "/query",
            json={"question": QUESTION, "scenario_id": SCENARIO_ID},
        )

    assert response.status_code == 200, response.text
    body = response.json()

    # Shape
    assert "answer" in body
    assert "affected_entities" in body
    assert "solver" in body
    assert "question" in body
    assert "scenario_id" in body

    # Stage 1 output (deterministic)
    assert set(body["affected_entities"]) == {ENTITY_A, ENTITY_B, ENTITY_C}

    # Stage 2 solver output
    assert body["solver"]["affected_count"] == 3
    assert body["solver"]["max_chain_length"] == 2
    assert body["solver"]["impact_score"] > 0
    assert isinstance(body["solver"]["response_options"], list)
    assert len(body["solver"]["response_options"]) > 0

    # Stage 3 synthesis
    assert isinstance(body["answer"], str)
    assert len(body["answer"]) > 0

    # Passthrough fields
    assert body["question"] == QUESTION
    assert body["scenario_id"] == SCENARIO_ID


@pytest.mark.asyncio
async def test_post_query_missing_required_fields():
    """POST /query with a missing field should return 422 Unprocessable Entity."""
    # Deps must be present so FastAPI can reach Pydantic validation;
    # the handler itself never runs when the body fails validation.
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[get_llm_client] = lambda: client
    app.dependency_overrides[get_solver] = lambda: StubSolver()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post("/query", json={"question": QUESTION})
            assert response.status_code == 422  # scenario_id missing

            response2 = await http.post("/query", json={"scenario_id": SCENARIO_ID})
            assert response2.status_code == 422  # question missing
    finally:
        app.dependency_overrides.pop(get_pool, None)
        app.dependency_overrides.pop(get_llm_client, None)
        app.dependency_overrides.pop(get_solver, None)
