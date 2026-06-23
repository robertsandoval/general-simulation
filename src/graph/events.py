"""Simulation event management — graph overlay + vector embedding.

A SimulationEvent is injected as an *overlay* on top of the base graph:
  - A SimulationEvent node is created in the AGE graph.
  - AFFECTED_BY edges connect each perturbed Entity to the event node.
  - The event description is ingested into a Llama Stack vector DB for RAG.

Crucially:
  - Base Entity nodes are NEVER modified.
  - Injecting an event is purely additive; removing it restores the original.
  - Multiple concurrent events (different scenario_id values) are fully
    independent — removing one leaves the others intact.

Vector DB naming: each scenario gets its own vector DB:
    f"sim_events_{scenario_id}"

This allows a whole scenario's vector data to be wiped in one
``unregister_vector_db`` call without affecting other scenarios.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import asyncpg

from src.graph.cypher import (
    cypher_read_sql,
    cypher_write_sql,
    parse_agtype_property,
)
from src.llamastack.base import LlamaStackClientBase

logger = logging.getLogger(__name__)

# Edge label connecting perturbed entities to a simulation event.
EDGE_AFFECTED_BY = "AFFECTED_BY"


def _vector_db_id(scenario_id: str) -> str:
    """Derive the vector DB identifier for a given scenario."""
    return f"sim_events_{scenario_id}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SimulationEvent:
    """An overlay event that perturbs one or more entities without mutating
    the live store.

    Attributes:
        id:                   Unique event identifier.  Also used as the
                              document_id in the vector store.
        scenario_id:          Groups events; multiple events with the same
                              scenario_id form a compound what-if scenario.
        description:          Human-readable text describing the perturbation.
                              This text is embedded and stored in the vector DB
                              for RAG retrieval during Stage-3 synthesis.
        affected_entity_ids:  Graph-node IDs of entities this event perturbs.
                              AFFECTED_BY edges are created for each one.
        attributes:           Arbitrary metadata (severity, category, etc.).
        created_at:           Timestamp of injection (set automatically).
    """

    id: str
    scenario_id: str
    description: str
    affected_entity_ids: list[str]
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Inject
# ---------------------------------------------------------------------------


async def inject_event(
    event: SimulationEvent,
    pool: asyncpg.Pool,
    llm_client: LlamaStackClientBase,
) -> None:
    """Inject a simulation event as an overlay.

    Steps (all additive — does NOT touch live-store or base entity nodes):
      1. Create a SimulationEvent node in the AGE graph.
      2. Create an AFFECTED_BY edge from each affected Entity to the event.
      3. Ingest the event description into the scenario's vector DB.

    Safe to call concurrently for different events / scenarios.
    """
    vdb = _vector_db_id(event.scenario_id)

    async with pool.acquire() as conn:
        # 1. Create the SimulationEvent node
        await _create_event_node(conn, event)

        # 2. Wire AFFECTED_BY edges
        for entity_id in event.affected_entity_ids:
            await _create_affected_by_edge(conn, entity_id, event.id)

    # 3. Ingest description into vector store (outside DB transaction)
    await llm_client.ensure_vector_db(vdb)
    await llm_client.ingest_documents(
        documents=[
            {
                "id": event.id,
                "content": event.description,
                "metadata": {
                    "scenario_id": event.scenario_id,
                    "event_id": event.id,
                    "affected_entity_ids": event.affected_entity_ids,
                    **event.attributes,
                },
            }
        ],
        vector_db_id=vdb,
    )

    logger.info(
        "Injected event: id=%s scenario=%s affected=%s",
        event.id,
        event.scenario_id,
        event.affected_entity_ids,
    )


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


async def remove_event(
    event_id: str,
    pool: asyncpg.Pool,
) -> None:
    """Remove a single simulation event from the graph.

    DETACH DELETE removes the SimulationEvent node and all its AFFECTED_BY
    edges in one operation.  Base Entity nodes are untouched.

    Note: the event's text remains in the vector DB until the whole scenario
    is removed via ``remove_scenario()``.  This is a Llama Stack v0.2.x
    limitation (no document-level deletion API).
    """
    query = "MATCH (e:SimulationEvent {id: $id}) DETACH DELETE e"
    async with pool.acquire() as conn:
        await conn.execute(cypher_write_sql(query), json.dumps({"id": event_id}))

    logger.info("Removed event from graph: id=%s", event_id)


async def remove_scenario(
    scenario_id: str,
    pool: asyncpg.Pool,
    llm_client: LlamaStackClientBase,
) -> None:
    """Remove ALL events belonging to *scenario_id* — graph and vector store.

    Graph: DETACH DELETE every SimulationEvent node with matching scenario_id.
    Vector: Unregister (drop) the scenario's vector DB, removing all embedded
            event descriptions cleanly.
    """
    query = (
        "MATCH (e:SimulationEvent {scenario_id: $sid}) DETACH DELETE e"
    )
    async with pool.acquire() as conn:
        await conn.execute(
            cypher_write_sql(query), json.dumps({"sid": scenario_id})
        )

    vdb = _vector_db_id(scenario_id)
    await llm_client.unregister_vector_db(vdb)

    logger.info("Removed scenario: id=%s vector_db=%s", scenario_id, vdb)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


async def get_affected_entities(
    conn: asyncpg.Connection,
    event_id: str,
) -> list[str]:
    """Return the IDs of all Entity nodes connected to *event_id* via
    AFFECTED_BY edges.

    Used by Stage-1 of the reasoning pipeline to collect the affected
    subgraph without touching the live store.
    """
    query = (
        "MATCH (n:Entity)-[:AFFECTED_BY]->(e:SimulationEvent {id: $id}) "
        "RETURN n.id AS entity_id"
    )
    rows = await conn.fetch(cypher_read_sql(query), json.dumps({"id": event_id}))
    return [
        prop
        for row in rows
        if (prop := parse_agtype_property(row["result"])) is not None
    ]


async def get_scenario_events(
    conn: asyncpg.Connection,
    scenario_id: str,
) -> list[str]:
    """Return event IDs belonging to *scenario_id*."""
    query = (
        "MATCH (e:SimulationEvent {scenario_id: $sid}) "
        "RETURN e.id AS event_id"
    )
    rows = await conn.fetch(
        cypher_read_sql(query), json.dumps({"sid": scenario_id})
    )
    return [
        prop
        for row in rows
        if (prop := parse_agtype_property(row["result"])) is not None
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _create_event_node(
    conn: asyncpg.Connection,
    event: SimulationEvent,
) -> None:
    query = (
        "CREATE (e:SimulationEvent {"
        "id: $id, "
        "scenario_id: $scenario_id, "
        "description: $description"
        "}) RETURN id(e)"
    )
    params = {
        "id": event.id,
        "scenario_id": event.scenario_id,
        "description": event.description,
    }
    await conn.execute(cypher_write_sql(query), json.dumps(params))


async def _create_affected_by_edge(
    conn: asyncpg.Connection,
    entity_id: str,
    event_id: str,
) -> None:
    query = (
        "MATCH (n:Entity {id: $entity_id}), "
        "(e:SimulationEvent {id: $event_id}) "
        f"CREATE (n)-[:{EDGE_AFFECTED_BY}]->(e) "
        "RETURN id(e)"
    )
    params = {"entity_id": entity_id, "event_id": event_id}
    await conn.execute(cypher_write_sql(query), json.dumps(params))
