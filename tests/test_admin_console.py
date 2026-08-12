"""Tests for new admin console API endpoints."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.deps import get_neo4j_driver, get_pool


def _pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.fetch = conn.fetch
    pool.fetchval = conn.fetchval
    return pool


def _neo4j_driver(*run_responses: list[dict[str, Any]]) -> MagicMock:
    responses = list(run_responses)
    response_iter = iter(responses)

    async def _run(*_args: Any, **_kwargs: Any) -> AsyncMock:
        result = AsyncMock()
        result.data = AsyncMock(return_value=next(response_iter, []))
        return result

    session_mock = AsyncMock()
    session_mock.run.side_effect = _run

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver


@pytest.fixture()
def override_pool():
    conn = AsyncMock()
    pool = _pool(conn)
    app.dependency_overrides[get_pool] = lambda: pool
    yield conn
    app.dependency_overrides.pop(get_pool, None)


@pytest.fixture()
def override_neo4j():
    driver = _neo4j_driver([{"id": "a"}, {"id": "c"}])
    app.dependency_overrides[get_neo4j_driver] = lambda: driver
    yield driver
    app.dependency_overrides.pop(get_neo4j_driver, None)


@pytest.mark.asyncio
async def test_sync_status(override_pool: AsyncMock, override_neo4j: MagicMock):
    override_pool.fetch.return_value = [{"id": "a"}, {"id": "b"}]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/data/sync-status")

    assert response.status_code == 200
    body = response.json()
    assert body["postgres_entity_count"] == 2
    assert body["neo4j_entity_count"] == 2
    assert body["postgres_only_count"] == 1
    assert body["neo4j_only_count"] == 1
    assert body["in_sync"] is False
    assert "b" in body["postgres_only_sample"]
    assert "c" in body["neo4j_only_sample"]


@pytest.mark.asyncio
async def test_list_ingestion_adapters():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/ingestion/adapters")

    assert response.status_code == 200
    body = response.json()
    assert "adapters" in body
    assert "enabled_domains" in body


@pytest.mark.asyncio
async def test_platform_config():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/platform/config")

    assert response.status_code == 200
    body = response.json()
    assert "llm_backend" in body
    assert "dependency_edge_types" in body
    assert "DEPENDS_ON" in body["dependency_edge_types"]
