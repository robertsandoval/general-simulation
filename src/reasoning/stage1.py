"""Stage 1 — Structural traversal (deterministic, no LLM).

Queries Apache AGE directly to collect:
  1. Every Entity node reachable via AFFECTED_BY edges from any
     SimulationEvent in the given scenario.
  2. Every dependency edge between those entities within the subgraph.

Output is an AffectedSubgraph ready for Stage 2.

Rules:
  - No LLM calls here.
  - Read-only — never mutates the graph.
  - All Cypher goes through ag_catalog.cypher() helpers from src.graph.cypher.
"""
from __future__ import annotations

import json
import logging

import asyncpg

from src.core.solver import AffectedSubgraph
from src.graph.cypher import cypher_read_sql, parse_agtype, parse_agtype_property

logger = logging.getLogger(__name__)


async def run_stage1(
    scenario_id: str,
    pool: asyncpg.Pool,
) -> AffectedSubgraph:
    """Collect the full affected subgraph for every event in *scenario_id*.

    Step A: MATCH all Entity nodes connected via AFFECTED_BY to any
            SimulationEvent whose scenario_id = *scenario_id*.
    Step B: MATCH all dependency edges between those entities (sub-DAG).

    Returns an empty subgraph if no events have been injected yet.
    """
    async with pool.acquire() as conn:
        entity_ids = await _get_affected_entities(conn, scenario_id)

        if not entity_ids:
            logger.info(
                "Stage 1: no affected entities found for scenario=%s", scenario_id
            )
            return AffectedSubgraph(
                event_id=f"scenario:{scenario_id}",
                scenario_id=scenario_id,
                affected_entity_ids=[],
            )

        edges = await _get_dependency_edges(conn, entity_ids)

    logger.info(
        "Stage 1 complete: scenario=%s entities=%d edges=%d",
        scenario_id,
        len(entity_ids),
        len(edges),
    )
    return AffectedSubgraph(
        event_id=f"scenario:{scenario_id}",
        scenario_id=scenario_id,
        affected_entity_ids=entity_ids,
        dependency_edges=edges,
    )


async def _get_affected_entities(
    conn: asyncpg.Connection,
    scenario_id: str,
) -> list[str]:
    """MATCH entities connected via AFFECTED_BY to any event in the scenario."""
    query = (
        "MATCH (n:Entity)-[:AFFECTED_BY]->(e:SimulationEvent {scenario_id: $sid}) "
        "RETURN DISTINCT n.id AS entity_id"
    )
    rows = await conn.fetch(
        cypher_read_sql(query),
        json.dumps({"sid": scenario_id}),
    )
    return [
        prop
        for row in rows
        if (prop := parse_agtype_property(row["result"])) is not None
    ]


async def _get_dependency_edges(
    conn: asyncpg.Connection,
    entity_ids: list[str],
) -> list[tuple[str, str, str]]:
    """MATCH dependency edges between the given entities (within subgraph)."""
    query = (
        "MATCH (a:Entity)-[r]->(b:Entity) "
        "WHERE a.id IN $ids AND b.id IN $ids "
        "RETURN {from_id: a.id, edge_type: type(r), to_id: b.id} AS edge"
    )
    rows = await conn.fetch(
        cypher_read_sql(query),
        json.dumps({"ids": entity_ids}),
    )
    edges: list[tuple[str, str, str]] = []
    for row in rows:
        parsed = parse_agtype(row["result"])
        if isinstance(parsed, dict):
            from_id = parsed.get("from_id")
            edge_type = parsed.get("edge_type")
            to_id = parsed.get("to_id")
            if from_id and edge_type and to_id:
                edges.append((str(from_id), str(to_id), str(edge_type)))
    return edges
