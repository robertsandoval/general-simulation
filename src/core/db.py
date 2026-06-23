"""Shared asyncpg connection pool factory.

Used by src.graph (Apache AGE / Cypher) and src.live (PostGIS).

Vector/RAG access is via the Llama Stack client — never via this module.
"""
from __future__ import annotations

import asyncpg

from src.core.config import Settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection initialisation.

    Apache AGE requires ag_catalog in the search_path for Cypher queries
    and ag_catalog function calls.  Setting it here guarantees every
    connection acquired from the pool is AGE-ready without callers having
    to remember to SET it themselves.
    """
    await conn.execute('SET search_path = ag_catalog, "$user", public')


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create and return a new asyncpg connection pool.

    The pool is configured for both AGE (Cypher) and PostGIS (geo) access.
    Callers are responsible for closing the pool on shutdown via
    ``await pool.close()``.
    """
    return await asyncpg.create_pool(
        settings.postgres_dsn,
        min_size=1,
        max_size=10,
        init=_init_connection,
    )
