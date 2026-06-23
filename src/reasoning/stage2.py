"""Stage 2 — Quantitative: live state read + solver.

Reads the *current* snapshot for affected entities from the PostGIS live
store (entity + entity_state tables), then runs the solver.

Rules:
  - READ ONLY — never writes to entity or entity_state.
  - Live state is read as-is; simulation overlays are applied only at query
    time by the reasoning pipeline, not by mutating DB rows.
  - No LLM calls here.
"""
from __future__ import annotations

import json
import logging

import asyncpg

from src.core.solver import (
    AffectedSubgraph,
    EntityState,
    LiveState,
    Solver,
    SolverResult,
)

logger = logging.getLogger(__name__)

# PostGIS query: latest state for each affected entity (read-only lateral join).
_LIVE_STATE_SQL = """
SELECT
    e.id,
    e.type,
    e.attributes AS entity_attrs,
    COALESCE(es.status, 'unknown')         AS status,
    COALESCE(es.attributes, '{}'::jsonb)   AS state_attrs
FROM entity e
LEFT JOIN LATERAL (
    SELECT status, attributes
    FROM   entity_state
    WHERE  entity_id = e.id
    ORDER  BY recorded_at DESC
    LIMIT  1
) es ON true
WHERE e.id = ANY($1::text[])
"""


async def run_stage2(
    subgraph: AffectedSubgraph,
    pool: asyncpg.Pool,
    solver: Solver,
) -> tuple[LiveState, SolverResult]:
    """Read live state and compute quantitative impact.

    Returns ``(live_state, solver_result)`` so Stage 3 can include live
    state context in its prompt if desired.
    """
    live_state = await _read_live_state(subgraph.affected_entity_ids, pool)
    solver_result = solver.solve(subgraph, live_state)

    logger.info(
        "Stage 2 complete: event=%s affected=%d impact=%.3f",
        subgraph.event_id,
        solver_result.affected_count,
        solver_result.impact_score,
    )
    return live_state, solver_result


async def _read_live_state(
    entity_ids: list[str],
    pool: asyncpg.Pool,
) -> LiveState:
    """Return the latest EntityState for each entity in *entity_ids*.

    Entities not found in the live store receive a default 'unknown' state
    (simulation events may reference entities whose ingestion is pending).
    """
    # Seed with unknowns so every ID has an entry even if not in DB
    live_state: LiveState = {
        eid: EntityState(entity_id=eid, status="unknown")
        for eid in entity_ids
    }

    if not entity_ids:
        return live_state

    async with pool.acquire() as conn:
        rows = await conn.fetch(_LIVE_STATE_SQL, entity_ids)

    for row in rows:
        entity_id = row["id"]
        entity_attrs = row["entity_attrs"]
        state_attrs = row["state_attrs"]

        # asyncpg returns JSONB as dict; handle str fallback just in case
        if isinstance(entity_attrs, str):
            entity_attrs = json.loads(entity_attrs)
        if isinstance(state_attrs, str):
            state_attrs = json.loads(state_attrs)

        live_state[entity_id] = EntityState(
            entity_id=entity_id,
            status=row["status"],
            attributes={**(entity_attrs or {}), **(state_attrs or {})},
        )

    return live_state
