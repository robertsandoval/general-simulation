"""Tests for the graph knowledge store — nodes, edges, and simulation events.

No live database or Llama Stack server required:
  - asyncpg connections are mocked
  - FakeLlamaStackClient provides the in-memory vector store

Build-plan "done when" checks:
  - inject_event: AFFECTED_BY edges created in graph + chunk retrievable via
    vector_search
  - remove_event: DETACH DELETE issued; base Entity nodes untouched
  - remove_scenario: graph cleaned + vector DB unregistered
"""
from __future__ import annotations

import json
from datetime import timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.core.config import Settings
from src.graph.cypher import (
    GRAPH_NAME,
    cypher_read_sql,
    cypher_write_sql,
    parse_agtype,
    parse_agtype_property,
)
from src.graph.events import (
    EDGE_AFFECTED_BY,
    SimulationEvent,
    _create_affected_by_edge,
    _create_event_node,
    get_affected_entities,
    get_scenario_events,
    inject_event,
    remove_event,
    remove_scenario,
)
from src.graph.nodes import (
    create_dependency_edge,
    create_entity_node,
    delete_entity_node,
    get_dependent_entities,
)
from src.llamastack.fake import FakeLlamaStackClient


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
    """Mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    return conn


def _pool(conn: AsyncMock) -> MagicMock:
    """Mock asyncpg pool that yields the given connection."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _event(
    event_id: str = "evt-1",
    scenario_id: str = "s1",
    affected: list[str] | None = None,
) -> SimulationEvent:
    return SimulationEvent(
        id=event_id,
        scenario_id=scenario_id,
        description="A major disruption affecting downstream entities.",
        affected_entity_ids=affected or ["entity-A", "entity-B"],
        attributes={"severity": "high"},
    )


# ── Cypher helpers ────────────────────────────────────────────────────────────


def test_cypher_write_sql_contains_graph_name():
    sql = cypher_write_sql("CREATE (n:Entity)")
    assert GRAPH_NAME in sql
    assert "ag_catalog.cypher" in sql
    assert "$1::agtype" in sql


def test_cypher_read_sql_contains_graph_name():
    sql = cypher_read_sql("MATCH (n) RETURN n")
    assert GRAPH_NAME in sql
    assert "ag_catalog.cypher" in sql


def test_parse_agtype_string():
    assert parse_agtype('"hello"') == "hello"


def test_parse_agtype_number():
    assert parse_agtype("42") == 42


def test_parse_agtype_strips_vertex_suffix():
    raw = '{"id": 1, "label": "Entity", "properties": {"id": "e1"}}::vertex'
    parsed = parse_agtype(raw)
    assert isinstance(parsed, dict)
    assert parsed["label"] == "Entity"


def test_parse_agtype_none():
    assert parse_agtype(None) is None


def test_parse_agtype_property_unwraps_json_string():
    assert parse_agtype_property('"entity-42"') == "entity-42"


def test_parse_agtype_property_none():
    assert parse_agtype_property(None) is None


# ── Entity node operations ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_entity_node_executes_cypher():
    conn = _conn()
    await create_entity_node(conn, "e1", "moving_entity")
    conn.execute.assert_awaited_once()
    sql, params_json = conn.execute.call_args.args
    assert "MERGE" in sql
    assert "Entity" in sql
    params = json.loads(params_json)
    assert params["id"] == "e1"
    assert params["type"] == "moving_entity"


@pytest.mark.asyncio
async def test_create_entity_node_with_attributes():
    conn = _conn()
    await create_entity_node(conn, "e2", "sensor", {"region": "west"})
    _, params_json = conn.execute.call_args.args
    params = json.loads(params_json)
    assert params.get("region") == "west"


@pytest.mark.asyncio
async def test_delete_entity_node_executes_detach_delete():
    conn = _conn()
    await delete_entity_node(conn, "e1")
    sql, params_json = conn.execute.call_args.args
    assert "DETACH DELETE" in sql
    assert json.loads(params_json)["id"] == "e1"


# ── Dependency edges ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_dependency_edge_uses_edge_type():
    conn = _conn()
    await create_dependency_edge(conn, "a", "b", "FEEDS")
    sql, params_json = conn.execute.call_args.args
    assert "FEEDS" in sql
    params = json.loads(params_json)
    assert params["from_id"] == "a"
    assert params["to_id"] == "b"


@pytest.mark.asyncio
async def test_create_dependency_edge_default_type():
    conn = _conn()
    await create_dependency_edge(conn, "a", "b")
    sql, _ = conn.execute.call_args.args
    assert "DEPENDS_ON" in sql


@pytest.mark.asyncio
async def test_get_dependent_entities_returns_parsed_ids():
    conn = _conn()
    # Simulate AGE returning agtype string rows
    conn.fetch = AsyncMock(
        return_value=[
            {"result": '"dep-entity-1"'},
            {"result": '"dep-entity-2"'},
        ]
    )
    deps = await get_dependent_entities(conn, "root-entity")
    assert deps == ["dep-entity-1", "dep-entity-2"]


@pytest.mark.asyncio
async def test_get_dependent_entities_empty():
    conn = _conn()
    conn.fetch = AsyncMock(return_value=[])
    deps = await get_dependent_entities(conn, "isolated")
    assert deps == []


# ── SimulationEvent dataclass ─────────────────────────────────────────────────


def test_simulation_event_fields():
    evt = _event()
    assert evt.id == "evt-1"
    assert evt.scenario_id == "s1"
    assert "entity-A" in evt.affected_entity_ids
    assert evt.created_at.tzinfo is not None


def test_simulation_event_default_created_at_is_utc():
    evt = _event()
    assert evt.created_at.tzinfo == timezone.utc


# ── inject_event ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inject_event_creates_event_node():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event()

    await inject_event(evt, pool, client)

    all_sqls = [c.args[0] for c in conn.execute.call_args_list]
    assert any("SimulationEvent" in sql for sql in all_sqls), (
        "Expected a CREATE (e:SimulationEvent ...) Cypher call"
    )


@pytest.mark.asyncio
async def test_inject_event_creates_affected_by_edges():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event(affected=["entity-A", "entity-B", "entity-C"])

    await inject_event(evt, pool, client)

    # 1 event-node CREATE + 3 AFFECTED_BY edges = 4 execute calls
    assert conn.execute.await_count == 4
    edge_calls = [
        c.args[0]
        for c in conn.execute.call_args_list
        if EDGE_AFFECTED_BY in c.args[0]
    ]
    assert len(edge_calls) == 3


@pytest.mark.asyncio
async def test_inject_event_embeds_description_in_vector_store():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event()

    await inject_event(evt, pool, client)

    vdb = f"sim_events_{evt.scenario_id}"
    results = await client.vector_search(evt.description, vdb, top_k=1)
    assert len(results) == 1
    assert results[0].document_id == evt.id


@pytest.mark.asyncio
async def test_inject_event_chunk_metadata_contains_scenario_id():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event()

    await inject_event(evt, pool, client)

    vdb = f"sim_events_{evt.scenario_id}"
    results = await client.vector_search(evt.description, vdb)
    assert results[0].metadata.get("scenario_id") == evt.scenario_id


@pytest.mark.asyncio
async def test_inject_multiple_events_same_scenario():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()

    evt1 = _event("evt-1", "s1", ["e1"])
    evt2 = _event("evt-2", "s1", ["e2"])

    await inject_event(evt1, pool, client)
    await inject_event(evt2, pool, client)

    vdb = "sim_events_s1"
    results = await client.vector_search("disruption", vdb, top_k=5)
    doc_ids = {r.document_id for r in results}
    assert "evt-1" in doc_ids
    assert "evt-2" in doc_ids


# ── get_affected_entities ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_affected_entities_returns_entity_ids():
    conn = _conn()
    conn.fetch = AsyncMock(
        return_value=[
            {"result": '"entity-A"'},
            {"result": '"entity-B"'},
        ]
    )
    ids = await get_affected_entities(conn, "evt-1")
    assert ids == ["entity-A", "entity-B"]
    sql = conn.fetch.call_args.args[0]
    assert "AFFECTED_BY" in sql
    assert "SimulationEvent" in sql


@pytest.mark.asyncio
async def test_get_affected_entities_empty_when_no_edges():
    conn = _conn()
    conn.fetch = AsyncMock(return_value=[])
    ids = await get_affected_entities(conn, "no-such-event")
    assert ids == []


# ── remove_event ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_event_issues_detach_delete():
    conn = _conn()
    pool = _pool(conn)

    await remove_event("evt-1", pool)

    conn.execute.assert_awaited_once()
    sql, params_json = conn.execute.call_args.args
    assert "DETACH DELETE" in sql
    assert "SimulationEvent" in sql
    assert json.loads(params_json)["id"] == "evt-1"


@pytest.mark.asyncio
async def test_remove_event_does_not_touch_entity_nodes():
    """DETACH DELETE on SimulationEvent must not delete Entity nodes."""
    conn = _conn()
    pool = _pool(conn)

    await remove_event("evt-1", pool)

    # The only execute call must target SimulationEvent, not Entity
    sql, _ = conn.execute.call_args.args
    assert "Entity" not in sql.split("SimulationEvent")[0], (
        "Entity nodes should not appear before SimulationEvent in the DELETE query"
    )


# ── remove_scenario ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_scenario_cleans_graph_and_vector():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event(scenario_id="s2")

    await inject_event(evt, pool, client)
    vdb = f"sim_events_{evt.scenario_id}"

    # Vector store has the event
    pre = await client.vector_search(evt.description, vdb)
    assert len(pre) > 0

    # Reset execute count before remove_scenario
    conn.execute.reset_mock()
    await remove_scenario(evt.scenario_id, pool, client)

    # Graph DELETE was issued
    conn.execute.assert_awaited_once()
    sql, params_json = conn.execute.call_args.args
    assert "DETACH DELETE" in sql
    assert json.loads(params_json)["sid"] == evt.scenario_id

    # Vector store is cleared
    post = await client.vector_search(evt.description, vdb)
    assert post == []


@pytest.mark.asyncio
async def test_remove_scenario_does_not_affect_other_scenarios():
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()

    evt_s1 = _event("evt-s1", "scenario-one", ["e1"])
    evt_s2 = _event("evt-s2", "scenario-two", ["e2"])

    await inject_event(evt_s1, pool, client)
    await inject_event(evt_s2, pool, client)

    conn.execute.reset_mock()
    await remove_scenario("scenario-one", pool, client)

    # scenario-two vector store should still exist
    results = await client.vector_search(
        evt_s2.description, "sim_events_scenario-two"
    )
    assert len(results) > 0


# ── Full round-trip: inject → query → remove → base graph intact ──────────────


@pytest.mark.asyncio
async def test_full_roundtrip_inject_remove():
    """Inject an event, retrieve it, remove it, confirm graph calls are correct."""
    conn = _conn()
    pool = _pool(conn)
    client = _fake_client()
    evt = _event("evt-rt", "rt-scenario", ["e1", "e2"])

    # Inject
    await inject_event(evt, pool, client)
    execute_after_inject = conn.execute.await_count  # 1 node + 2 edges = 3

    assert execute_after_inject == 3

    # Vector store has the event
    vdb = "sim_events_rt-scenario"
    hits = await client.vector_search(evt.description, vdb, top_k=1)
    assert hits[0].document_id == "evt-rt"

    # Remove scenario (full cleanup)
    conn.execute.reset_mock()
    await remove_scenario(evt.scenario_id, pool, client)

    # One DELETE call issued
    assert conn.execute.await_count == 1
    delete_sql, _ = conn.execute.call_args.args
    assert "DETACH DELETE" in delete_sql

    # Vector store is now empty
    post_hits = await client.vector_search(evt.description, vdb)
    assert post_hits == []
