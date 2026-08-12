"""Commit a validated ImportDraft to PostGIS + Neo4j."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
from neo4j import AsyncDriver

from src.core.ingestion import CanonicalEntity
from src.graph.nodes import merge_dependency_edges, merge_entity_nodes
from src.importers.models import ImportDraft, ImportResult
from src.ingestion.runner import _insert_state, _upsert_entity

logger = logging.getLogger(__name__)


async def commit_import(
    draft: ImportDraft,
    *,
    pool: asyncpg.Pool,
    neo4j_driver: AsyncDriver,
    dataset_id: str | None = None,
) -> ImportResult:
    """Upsert entities to Postgres and Neo4j; MERGE dependency edges.

    Caller must validate the draft first (``draft.ok``).
    """
    if not draft.ok:
        raise ValueError(
            f"Cannot commit import with {draft.error_count} error(s)"
        )

    now = datetime.now(timezone.utc)
    canonical: list[CanonicalEntity] = [
        CanonicalEntity(
            id=e.id,
            type=e.type,
            timestamp=now,
            status=e.status,
            geometry=e.geometry,
            attributes=e.attributes,
        )
        for e in draft.entities
    ]

    if canonical:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for entity in canonical:
                    await _upsert_entity(conn, entity)
                    await _insert_state(conn, entity)

        await merge_entity_nodes(
            neo4j_driver,
            [
                {
                    "id": e.id,
                    "type": e.type,
                    "dataset_id": dataset_id
                    or e.attributes.get("dataset_id"),
                }
                for e in draft.entities
            ],
        )

    edges_merged = 0
    if draft.edges:
        edges_merged = await merge_dependency_edges(
            neo4j_driver,
            [
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "edge_type": e.edge_type,
                }
                for e in draft.edges
            ],
        )

    logger.info(
        "Import committed: entities=%d edges=%d dataset_id=%s",
        len(canonical),
        edges_merged,
        dataset_id,
    )
    return ImportResult(
        entities_upserted=len(canonical),
        edges_merged=edges_merged,
        dataset_id=dataset_id,
    )


def draft_to_jsonable(draft: ImportDraft) -> dict:
    """Serialize a draft for API responses."""
    return {
        "entities": [
            {
                "id": e.id,
                "type": e.type,
                "status": e.status,
                "geometry": e.geometry,
                "attributes": e.attributes,
            }
            for e in draft.entities
        ],
        "edges": [
            {
                "from_id": e.from_id,
                "to_id": e.to_id,
                "edge_type": e.edge_type,
            }
            for e in draft.edges
        ],
        "issues": [
            {"level": i.level, "message": i.message, "row": i.row}
            for i in draft.issues
        ],
        "detected_columns": draft.detected_columns,
        "entity_count": len(draft.entities),
        "edge_count": len(draft.edges),
        "error_count": draft.error_count,
        "warning_count": draft.warning_count,
        "ok": draft.ok,
    }
