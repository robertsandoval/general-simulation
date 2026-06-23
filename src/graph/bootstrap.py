"""Idempotent schema bootstrap.

Creates (or no-ops if already present):
  - PostgreSQL extensions: age, vector, postgis
  - The Apache AGE graph: sim_graph
  - Live-store tables:     entity, entity_state  (PostGIS + JSONB, domain-agnostic)

Run directly:
    uv run python -m src.graph.bootstrap

Or import and call from application / test code:
    await bootstrap(dsn="postgresql://...")

Assumptions:
  - Postgres is running with ``shared_preload_libraries = 'age'``.
    Without this, CREATE EXTENSION age will fail.
  - The connecting role has SUPERUSER or at least CREATEEXT privilege.

Safe to re-run on an already-bootstrapped database.
"""
from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg

from src.core.config import Settings

logger = logging.getLogger(__name__)

AGE_GRAPH_NAME = "sim_graph"

# ---------------------------------------------------------------------------
# SQL statements executed in order.
# Every statement is idempotent (IF NOT EXISTS / DO ... IF NOT EXISTS block).
# ---------------------------------------------------------------------------

_EXTENSION_STATEMENTS: list[str] = [
    # AGE must come first; its ag_catalog schema is used in later statements.
    "CREATE EXTENSION IF NOT EXISTS age",
    # vector extension — Llama Stack's pgvector provider manages its own tables;
    # we only guarantee the extension exists.
    "CREATE EXTENSION IF NOT EXISTS vector",
    # PostGIS for geometry columns in entity / entity_state.
    "CREATE EXTENSION IF NOT EXISTS postgis",
]

_AGE_GRAPH_STATEMENT = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   ag_catalog.ag_graph
        WHERE  name = '{AGE_GRAPH_NAME}'
    ) THEN
        PERFORM ag_catalog.create_graph('{AGE_GRAPH_NAME}');
        RAISE NOTICE 'AGE graph "%s" created', '{AGE_GRAPH_NAME}';
    ELSE
        RAISE NOTICE 'AGE graph "%s" already exists — skipping', '{AGE_GRAPH_NAME}';
    END IF;
END;
$$
"""

# Domain-agnostic live-store tables.  No domain columns — all domain
# specifics live in the JSONB `attributes` field.
_TABLE_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS entity (
        id          TEXT        PRIMARY KEY,
        type        TEXT        NOT NULL,
        geometry    geometry(Geometry, 4326),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        attributes  JSONB       NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_state (
        id          BIGSERIAL   PRIMARY KEY,
        entity_id   TEXT        NOT NULL
                        REFERENCES entity(id) ON DELETE CASCADE,
        status      TEXT        NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        attributes  JSONB       NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_entity_type         ON entity (type)",
    # Partial index: only rows that actually have a geometry
    "CREATE INDEX IF NOT EXISTS idx_entity_geometry     ON entity USING GIST (geometry) WHERE geometry IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_entity_state_entity ON entity_state (entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_entity_state_time   ON entity_state (recorded_at DESC)",
]


async def bootstrap(dsn: str) -> None:
    """Run all bootstrap DDL against *dsn*.  Safe to call repeatedly."""
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        logger.info("Starting schema bootstrap …")

        # 1. Extensions
        for stmt in _EXTENSION_STATEMENTS:
            logger.debug("exec: %s", stmt.strip())
            await conn.execute(stmt)
        logger.info("Extensions ready (age, vector, postgis)")

        # 2. Set search_path so ag_catalog is visible for the AGE graph step.
        await conn.execute('SET search_path = ag_catalog, "$user", public')

        # 3. AGE graph
        await conn.execute(_AGE_GRAPH_STATEMENT)
        logger.info("AGE graph '%s' ready", AGE_GRAPH_NAME)

        # 4. Live-store tables and indexes (single transaction for atomicity)
        async with conn.transaction():
            for stmt in _TABLE_STATEMENTS:
                logger.debug("exec: %s", stmt.strip()[:80])
                await conn.execute(stmt)
        logger.info("Live-store tables and indexes ready")

        logger.info("Bootstrap complete.")

    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s — %(message)s",
    )
    settings = Settings()
    asyncio.run(bootstrap(settings.postgres_dsn))


if __name__ == "__main__":
    sys.exit(main())  # type: ignore[arg-type]
