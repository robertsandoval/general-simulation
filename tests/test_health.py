"""Smoke test for GET /health.

The DB check is mocked so the test runs without a live Postgres instance.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.api.health import get_settings
from src.core.config import Settings


def _test_settings() -> Settings:
    return Settings(
        postgres_dsn="postgresql://mock:mock@localhost:5432/mock",
        llama_stack_base_url="http://localhost:8321",
    )


app.dependency_overrides[get_settings] = _test_settings


@pytest.mark.asyncio
async def test_health_db_reachable():
    with patch(
        "src.api.health._check_db",
        new_callable=AsyncMock,
        return_value=True,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "reachable"


@pytest.mark.asyncio
async def test_health_db_unreachable():
    with patch(
        "src.api.health._check_db",
        new_callable=AsyncMock,
        return_value=False,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"
