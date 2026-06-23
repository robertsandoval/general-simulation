"""Generic Entity node and dependency edge operations via Apache AGE (Cypher).

Domain rule: NO domain-specific labels or property names here.
  - Nodes are always labelled ``Entity``; their domain type is a *property*.
  - Dependency semantics live in the edge type string (e.g. ``DEPENDS_ON``,
    ``FEEDS``, ``SUPPLIES``); callers choose the string, this module does not.

All writes go directly to Postgres/AGE — not through Llama Stack (which has
no graph provider).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from src.graph.cypher import (
    cypher_read_sql,
    cypher_write_sql,
    cypher_write_sql_no_params,
    parse_agtype_property,
)

logger = logging.getLogger(__name__)

# Supported edge types for dependency relationships.
# Callers may use any string; these are documented defaults.
EDGE_DEPENDS_ON = "DEPENDS_ON"
EDGE_FEEDS = "FEEDS"


# ---------------------------------------------------------------------------
# Entity node operations
# ---------------------------------------------------------------------------


async def create_entity_node(
    conn: asyncpg.Connection,
    entity_id: str,
    entity_type: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """MERGE an Entity node into the graph.

    Idempotent: safe to call for an entity that already exists.
    Existing node properties are updated with the supplied values.
    """
    params: dict[str, Any] = {
        "id": entity_id,
        "type": entity_type,
        **(attributes or {}),
    }
    # MERGE: create if not exists, then SET properties.
    query = (
        "MERGE (n:Entity {id: $id}) "
        "SET n.type = $type "
        "RETURN id(n)"
    )
    await conn.execute(cypher_write_sql(query), json.dumps(params))
    logger.debug("Entity node upserted: id=%s type=%s", entity_id, entity_type)


async def delete_entity_node(
    conn: asyncpg.Connection,
    entity_id: str,
) -> None:
    """Remove an Entity node and all its edges.

    Use with caution — this permanently removes the node and all relationships.
    Simulation events (SimulationEvent nodes) should be removed via
    ``remove_event()`` in ``src.graph.events``, not this function.
    """
    query = "MATCH (n:Entity {id: $id}) DETACH DELETE n"
    await conn.execute(cypher_write_sql(query), json.dumps({"id": entity_id}))
    logger.debug("Entity node deleted: id=%s", entity_id)


async def get_entity_node(
    conn: asyncpg.Connection,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return the properties of an Entity node, or None if not found."""
    query = "MATCH (n:Entity {id: $id}) RETURN properties(n) AS props"
    rows = await conn.fetch(cypher_read_sql(query), json.dumps({"id": entity_id}))
    if not rows:
        return None
    from src.graph.cypher import parse_agtype
    return parse_agtype(rows[0]["result"])


# ---------------------------------------------------------------------------
# Dependency edge operations
# ---------------------------------------------------------------------------


async def create_dependency_edge(
    conn: asyncpg.Connection,
    from_id: str,
    to_id: str,
    edge_type: str = EDGE_DEPENDS_ON,
) -> None:
    """Create a directed dependency edge from *from_id* to *to_id*.

    The edge is labelled with *edge_type* (default: ``DEPENDS_ON``).
    If the edge already exists, a duplicate is created — call
    ``delete_dependency_edge`` first if you want a single edge.
    """
    query = (
        "MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id}) "
        f"CREATE (a)-[:{edge_type}]->(b) "
        "RETURN id(a)"
    )
    params = {"from_id": from_id, "to_id": to_id}
    await conn.execute(cypher_write_sql(query), json.dumps(params))
    logger.debug(
        "Dependency edge created: %s -[%s]-> %s", from_id, edge_type, to_id
    )


async def get_dependent_entities(
    conn: asyncpg.Connection,
    entity_id: str,
    edge_type: str | None = None,
) -> list[str]:
    """Return the IDs of entities that *entity_id* depends on.

    When *edge_type* is None, all outgoing dependency edges are followed.
    """
    if edge_type:
        query = (
            f"MATCH (a:Entity {{id: $id}})-[:{edge_type}]->(b:Entity) "
            "RETURN b.id AS dep_id"
        )
    else:
        query = (
            "MATCH (a:Entity {id: $id})-[]->(b:Entity) "
            "RETURN b.id AS dep_id"
        )
    rows = await conn.fetch(cypher_read_sql(query), json.dumps({"id": entity_id}))
    return [
        prop
        for row in rows
        if (prop := parse_agtype_property(row["result"])) is not None
    ]
