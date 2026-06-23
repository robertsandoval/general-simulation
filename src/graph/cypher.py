"""AGE Cypher helpers.

All direct Postgres/AGE interaction goes through these utilities:
  - ``cypher_write_sql``  — build a SQL string for write-only Cypher
  - ``cypher_read_sql``   — build a SQL string for Cypher that returns rows
  - ``parse_agtype``      — decode an asyncpg agtype column value
  - ``GRAPH_NAME``        — single canonical graph name for the project

Rule: never import AGE-specific symbols from here into non-graph packages.
      The rest of the app knows nothing about AGE.
"""
from __future__ import annotations

import json
import re
from typing import Any

GRAPH_NAME = "sim_graph"

# Placeholder column declaration used when the Cypher query may return rows.
# AGE always requires an AS (...) clause on cypher(); this is the default.
_COL_DECL = "AS (result agtype)"


def cypher_write_sql(query: str) -> str:
    """Return a SQL string that executes *query* as a write-only Cypher call.

    Use with ``conn.execute(sql, json.dumps(params))`` for parameterised
    queries, or ``conn.execute(sql)`` for parameter-free ones.

    Example::

        sql = cypher_write_sql("MATCH (n:Entity {id: $id}) DETACH DELETE n")
        await conn.execute(sql, json.dumps({"id": "e1"}))
    """
    return (
        f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$ {query} $$"
        ", $1::agtype) AS (r agtype)"
    )


def cypher_write_sql_no_params(query: str) -> str:
    """Variant without parameters (no $1 placeholder)."""
    return (
        f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$ {query} $$)"
        " AS (r agtype)"
    )


def cypher_read_sql(query: str) -> str:
    """Return a SQL string that executes *query* as a read Cypher call.

    Use with ``conn.fetch(sql, json.dumps(params))`` to retrieve rows.

    Example::

        sql = cypher_read_sql(
            "MATCH (n)-[:AFFECTED_BY]->(e:SimulationEvent {id: $eid}) "
            "RETURN n.id AS entity_id"
        )
        rows = await conn.fetch(sql, json.dumps({"eid": event_id}))
    """
    return (
        f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$ {query} $$"
        ", $1::agtype) AS (result agtype)"
    )


def parse_agtype(raw: Any) -> Any:
    """Convert an asyncpg agtype column value into a Python object.

    AGE returns agtype values as text representations like::

        "entity-1"                                                  # string
        42                                                          # integer
        {"id": 123, "label": "Entity", "properties": {...}}::vertex

    The ``::vertex`` / ``::edge`` suffix is stripped; then the value is
    JSON-decoded.  Falls back to the raw string on decode failure.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    # Strip trailing AGE type annotation (::vertex, ::edge, ::path, etc.)
    s = re.sub(r"::(vertex|edge|path|vle)\s*$", "", s).strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


def parse_agtype_property(raw: Any) -> str | None:
    """Parse an agtype value that is expected to be a simple string property.

    AGE returns string properties as JSON strings, e.g. ``"entity-1"``
    (with surrounding quotes).  This helper unwraps that to a bare Python
    string, or returns None if the value is null / unparseable.
    """
    parsed = parse_agtype(raw)
    if parsed is None:
        return None
    if isinstance(parsed, str):
        return parsed
    # Numeric/bool property returned as-is
    return str(parsed)
