"""Smoke tests for the schema bootstrap.

All Postgres I/O is mocked — no live database required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.graph.bootstrap import (
    AGE_GRAPH_NAME,
    _EXTENSION_STATEMENTS,
    _TABLE_STATEMENTS,
    bootstrap,
)


def _make_conn_mock() -> AsyncMock:
    """Return an AsyncMock that acts like an asyncpg.Connection."""
    conn = AsyncMock()
    # Make conn.transaction() a sync context manager returning an AsyncMock
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


@pytest.mark.asyncio
async def test_bootstrap_calls_all_extension_statements():
    conn = _make_conn_mock()
    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        await bootstrap("postgresql://mock:mock@localhost/mock")

    executed = [c.args[0].strip() for c in conn.execute.call_args_list]

    for stmt in _EXTENSION_STATEMENTS:
        assert stmt.strip() in executed, f"Expected '{stmt.strip()}' to be executed"


@pytest.mark.asyncio
async def test_bootstrap_sets_search_path_before_age_graph():
    conn = _make_conn_mock()
    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        await bootstrap("postgresql://mock:mock@localhost/mock")

    executed = [c.args[0].strip() for c in conn.execute.call_args_list]

    search_path_idx = next(
        i for i, s in enumerate(executed)
        if "search_path" in s and "ag_catalog" in s
    )
    age_graph_idx = next(
        i for i, s in enumerate(executed)
        if AGE_GRAPH_NAME in s
    )
    assert search_path_idx < age_graph_idx, (
        "search_path must be set before AGE graph creation"
    )


@pytest.mark.asyncio
async def test_bootstrap_creates_all_tables():
    conn = _make_conn_mock()
    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        await bootstrap("postgresql://mock:mock@localhost/mock")

    executed = "\n".join(c.args[0] for c in conn.execute.call_args_list)

    assert "CREATE TABLE IF NOT EXISTS entity" in executed
    assert "CREATE TABLE IF NOT EXISTS entity_state" in executed


@pytest.mark.asyncio
async def test_bootstrap_creates_indexes():
    conn = _make_conn_mock()
    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        await bootstrap("postgresql://mock:mock@localhost/mock")

    executed = "\n".join(c.args[0] for c in conn.execute.call_args_list)

    assert "idx_entity_type" in executed
    assert "idx_entity_geometry" in executed
    assert "idx_entity_state_entity" in executed
    assert "idx_entity_state_time" in executed


@pytest.mark.asyncio
async def test_bootstrap_closes_connection_on_success():
    conn = _make_conn_mock()
    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        await bootstrap("postgresql://mock:mock@localhost/mock")

    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_closes_connection_on_error():
    conn = _make_conn_mock()
    conn.execute.side_effect = [None, RuntimeError("db error")]

    with patch("asyncpg.connect", new_callable=AsyncMock, return_value=conn):
        with pytest.raises(RuntimeError, match="db error"):
            await bootstrap("postgresql://mock:mock@localhost/mock")

    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_pool_sets_search_path():
    """create_pool init callback sets search_path for every connection."""
    from src.core.config import Settings
    from src.core.db import _init_connection

    conn = AsyncMock()
    await _init_connection(conn)

    conn.execute.assert_awaited_once()
    executed = conn.execute.call_args.args[0]
    assert "ag_catalog" in executed
    assert "search_path" in executed
