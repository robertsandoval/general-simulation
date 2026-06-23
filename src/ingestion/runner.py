"""Ingestion runner.

Calls an IngestionAdapter, normalises the result, and upserts canonical
entities into the PostGIS live store (entity + entity_state tables).

This module writes *ground-truth data only*.  Simulations are overlays
applied at query time and must never be written here.

Callable two ways (BUILD_PLAN task 4):
  1. CLI / one-shot  — ``python -m src.ingestion`` (OpenShift CronJob)
  2. Programmatic    — ``await run_ingestion(adapter, pool)``
     (the reasoning layer calls this via the Llama Stack tool wrapper)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg

from src.core.ingestion import CanonicalEntity, IngestionAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL helpers (kept here so the tool wrapper doesn't duplicate them)
# ---------------------------------------------------------------------------

_UPSERT_ENTITY = """
INSERT INTO entity (id, type, geometry, created_at, updated_at, attributes)
VALUES (
    $1,
    $2,
    CASE
        WHEN $3::text IS NOT NULL
        THEN ST_SetSRID(ST_GeomFromGeoJSON($3::text), 4326)
        ELSE NULL
    END,
    NOW(),
    NOW(),
    $4::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    type       = EXCLUDED.type,
    geometry   = EXCLUDED.geometry,
    updated_at = NOW(),
    attributes = EXCLUDED.attributes
"""

_INSERT_STATE = """
INSERT INTO entity_state (entity_id, status, recorded_at, attributes)
VALUES ($1, $2, $3, $4::jsonb)
"""


# ---------------------------------------------------------------------------
# Public callable
# ---------------------------------------------------------------------------


async def run_ingestion(
    adapter: IngestionAdapter,
    pool: asyncpg.Pool,
) -> int:
    """Execute one ingestion cycle for *adapter*.

    Returns the number of entities upserted.  All writes are in a single
    transaction — partial failures roll back cleanly.
    """
    logger.info("Starting ingestion: adapter=%s", adapter.adapter_id)

    raw = await adapter.fetch()
    entities: list[CanonicalEntity] = adapter.normalize(raw)

    if not entities:
        logger.info("adapter=%s returned 0 entities — nothing to upsert", adapter.adapter_id)
        return 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for entity in entities:
                await _upsert_entity(conn, entity)
                await _insert_state(conn, entity)

    logger.info(
        "Ingestion complete: adapter=%s upserted=%d",
        adapter.adapter_id,
        len(entities),
    )
    return len(entities)


# ---------------------------------------------------------------------------
# Internal helpers (also used by tests via direct import)
# ---------------------------------------------------------------------------


async def _upsert_entity(
    conn: asyncpg.Connection,
    entity: CanonicalEntity,
) -> None:
    geo_json: str | None = (
        json.dumps(entity.geometry) if entity.geometry else None
    )
    attrs = json.dumps(entity.attributes)
    await conn.execute(_UPSERT_ENTITY, entity.id, entity.type, geo_json, attrs)


async def _insert_state(
    conn: asyncpg.Connection,
    entity: CanonicalEntity,
) -> None:
    ts = entity.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    await conn.execute(
        _INSERT_STATE,
        entity.id,
        entity.status,
        ts,
        "{}",  # state-specific attributes; domain adapters can extend this
    )
