"""Validate an ImportDraft before commit."""
from __future__ import annotations

from neo4j import AsyncDriver

from src.graph.cypher import neo4j_session
from src.importers.models import ALLOWED_EDGE_TYPES, ImportDraft, ImportIssue


async def validate_draft(
    draft: ImportDraft,
    *,
    neo4j_driver: AsyncDriver | None = None,
    allow_existing_endpoints: bool = True,
) -> ImportDraft:
    """Append validation issues; returns the same draft for chaining.

    When *allow_existing_endpoints* is True and *neo4j_driver* is set, edge
    endpoints may resolve to Entity nodes already in Neo4j (edges-only import).
    """
    seen_ids: set[str] = set()
    for i, entity in enumerate(draft.entities, start=1):
        if not entity.id:
            draft.issues.append(
                ImportIssue(level="error", message="Empty entity id", row=i)
            )
            continue
        if entity.id in seen_ids:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Duplicate entity id {entity.id!r}",
                    row=i,
                )
            )
        seen_ids.add(entity.id)
        if not entity.type:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Entity {entity.id!r} missing type",
                    row=i,
                )
            )

    existing: set[str] = set()
    if allow_existing_endpoints and neo4j_driver is not None and draft.edges:
        needed = {e.from_id for e in draft.edges} | {e.to_id for e in draft.edges}
        missing_locally = needed - seen_ids
        if missing_locally:
            existing = await _lookup_entity_ids(neo4j_driver, missing_locally)

    known = seen_ids | existing

    for i, edge in enumerate(draft.edges, start=1):
        if edge.edge_type not in ALLOWED_EDGE_TYPES:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=(
                        f"Edge type {edge.edge_type!r} not allowed; "
                        f"use one of {sorted(ALLOWED_EDGE_TYPES)}"
                    ),
                    row=i,
                )
            )
        if edge.from_id not in known:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Edge from_id {edge.from_id!r} not found in import or graph",
                    row=i,
                )
            )
        if edge.to_id not in known:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Edge to_id {edge.to_id!r} not found in import or graph",
                    row=i,
                )
            )
        if edge.from_id == edge.to_id:
            draft.issues.append(
                ImportIssue(
                    level="warning",
                    message=f"Self-loop edge on {edge.from_id!r}",
                    row=i,
                )
            )

    if not draft.entities and not draft.edges:
        draft.issues.append(
            ImportIssue(
                level="error",
                message="Import contains no entities or edges",
            )
        )

    return draft


async def _lookup_entity_ids(
    driver: AsyncDriver, ids: set[str]
) -> set[str]:
    if not ids:
        return set()
    query = (
        "MATCH (n:Entity) WHERE n.id IN $ids RETURN n.id AS id"
    )
    async with neo4j_session(driver) as session:
        result = await session.run(query, ids=list(ids))
        records = await result.data()
    return {r["id"] for r in records if r.get("id")}
