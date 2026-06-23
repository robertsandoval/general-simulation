"""FastAPI application factory with lifespan resource management."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.api.health import router as health_router
from src.api.query import router as query_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared resources on startup; clean up on shutdown."""
    from src.core.config import Settings
    from src.core.db import create_pool
    from src.llamastack.factory import get_llama_stack_client
    from src.solver.stub import StubSolver

    settings = Settings()

    pool = None
    try:
        pool = await create_pool(settings)
        logger.info("DB pool ready")
    except Exception as exc:
        logger.warning("Could not create DB pool at startup: %s", exc)

    app.state.pool = pool
    app.state.llm_client = get_llama_stack_client(settings)
    app.state.solver = StubSolver()

    yield

    if pool is not None:
        await pool.close()
        logger.info("DB pool closed")


app = FastAPI(
    title="General Simulation & Impact-Reasoning Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(query_router)
