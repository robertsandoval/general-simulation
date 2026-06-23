from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends

from src.core.config import Settings

router = APIRouter()


def get_settings() -> Settings:
    return Settings()


async def _check_db(dsn: str) -> bool:
    """Attempt a single round-trip to Postgres; return True on success."""
    try:
        conn = await asyncpg.connect(dsn, timeout=3)
        await conn.execute("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False


@router.get("/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]):
    db_ok = await _check_db(settings.postgres_dsn)
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "reachable" if db_ok else "unreachable",
    }
