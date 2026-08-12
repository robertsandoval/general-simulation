"""Admin interface — browse Postgres entities and Neo4j graph data.

All routes are mounted under /admin.  The HTML SPA is served at GET /admin/
and makes same-origin API calls to the endpoints below.

Endpoint summary
----------------
GET  /admin/                       Serve the admin SPA (HTML)
GET  /admin/stats                  Overview counts (Postgres + graph)
GET  /admin/entity-types           Distinct entity types in Postgres
GET  /admin/entities               Paginated entity list (Postgres)
GET  /admin/entities/geojson       GeoJSON FeatureCollection (entities with geometry)
GET  /admin/entities/{id}          Entity detail + state history
GET  /admin/graph/nodes            Entity nodes from Neo4j graph
GET  /admin/graph/scenarios        Distinct scenario IDs from Neo4j
GET  /admin/graph/events           SimulationEvent nodes (optional filter)
GET  /admin/graph/edges            Dependency / AFFECTED_BY edges
POST /admin/graph/events           Inject a new simulation event
POST /admin/graph/scenarios/{id}/sync-spatial  Refresh AFFECTED_BY from PostGIS bbox
DELETE /admin/graph/scenarios/{id} Remove scenario from graph + vector DB
POST /admin/graph/dependency-edges       Create MERGE dependency edge
DELETE /admin/graph/dependency-edges     Remove dependency edge
GET  /admin/data/sync-status             Postgres vs Neo4j entity drift
GET  /admin/entities/in-bbox             Entity IDs inside a WGS84 bbox
GET  /admin/ingestion/adapters           Enabled ingestion adapters
POST /admin/ingestion/run                On-demand ingestion run
GET  /admin/platform/config              Read-only platform settings
POST /admin/platform/bootstrap           Idempotent schema bootstrap
POST /admin/imports/preview        Parse + validate uploaded graph file(s)
POST /admin/imports/commit         Upsert entities + MERGE dependency edges
GET  /admin/imports/formats        Supported formats and edge types
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from neo4j import AsyncDriver
from pydantic import BaseModel, Field

from src.api.deps import get_llm_client, get_neo4j_driver, get_pool
from src.core.config import Settings
from src.graph.bootstrap import bootstrap
from src.graph.cypher import neo4j_session
from src.graph.events import SimulationEvent, inject_event, remove_scenario
from src.graph.nodes import (
    ALLOWED_DEPENDENCY_EDGE_TYPES,
    EDGE_DEPENDS_ON,
    create_dependency_edge,
    delete_dependency_edge,
    merge_dependency_edges,
)
from src.graph.spatial_overlay import list_entities_in_bbox, parse_bbox
from src.importers.commit import commit_import, draft_to_jsonable
from src.importers.models import ImportMapping
from src.importers.parse import parse_import
from src.importers.validate import validate_draft
from src.ingestion.registry import get_adapter_class, list_adapter_catalog
from src.ingestion.runner import run_ingestion
from src.llm.base import LLMClientBase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_STATIC = Path(__file__).parent / "static"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB per file


# ── UI ────────────────────────────────────────────────────────────────────────

@router.get("/", include_in_schema=False)
async def admin_ui() -> FileResponse:
    """Serve the admin SPA."""
    return FileResponse(_STATIC / "admin.html")


# ── Overview stats ────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    pool: asyncpg.Pool = Depends(get_pool),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, int]:
    """Return aggregate counts from Postgres and the Neo4j graph."""
    entity_count: int = await pool.fetchval("SELECT COUNT(*) FROM entity") or 0
    state_count: int = await pool.fetchval("SELECT COUNT(*) FROM entity_state") or 0

    async with neo4j_session(driver) as session:
        node_result = await session.run("MATCH (n:Entity) RETURN count(n) AS cnt")
        node_record = await node_result.single()
        graph_nodes: int = node_record["cnt"] if node_record else 0

        event_result = await session.run("MATCH (e:SimulationEvent) RETURN count(e) AS cnt")
        event_record = await event_result.single()
        graph_events: int = event_record["cnt"] if event_record else 0

        scenario_result = await session.run(
            "MATCH (e:SimulationEvent) RETURN DISTINCT e.scenario_id AS sid"
        )
        scenario_records = await scenario_result.data()
        scenario_count = len([r for r in scenario_records if r.get("sid")])

    return {
        "entity_count": entity_count,
        "state_count": state_count,
        "graph_nodes": graph_nodes,
        "graph_events": graph_events,
        "scenario_count": scenario_count,
    }


# ── Postgres: entities ────────────────────────────────────────────────────────

@router.get("/entity-types")
async def list_entity_types(pool: asyncpg.Pool = Depends(get_pool)) -> list[str]:
    """Return distinct entity types present in the live store."""
    rows = await pool.fetch("SELECT DISTINCT type FROM entity ORDER BY type")
    return [r["type"] for r in rows]


@router.get("/entities")
async def list_entities(
    type: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return a paginated list of entities from the live Postgres store."""
    conditions: list[str] = []
    args: list[Any] = []

    if type:
        args.append(type)
        conditions.append(f"type = ${len(args)}")
    if search:
        args.append(f"%{search}%")
        conditions.append(f"id ILIKE ${len(args)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total: int = await pool.fetchval(
        f"SELECT COUNT(*) FROM entity {where}", *args
    ) or 0

    page_args = args + [limit, offset]
    rows = await pool.fetch(
        f"SELECT id, type, attributes, created_at, updated_at "
        f"FROM entity {where} ORDER BY updated_at DESC "
        f"LIMIT ${len(page_args) - 1} OFFSET ${len(page_args)}",
        *page_args,
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r["id"],
                "type": r["type"],
                "attributes": json.loads(r["attributes"]) if r["attributes"] else {},
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/entities/geojson")
async def list_entities_geojson(
    type: str | None = Query(None, description="Filter by entity type"),
    bbox: str | None = Query(
        None,
        description="Optional bbox: minLon,minLat,maxLon,maxLat (WGS84)",
    ),
    ids: str | None = Query(
        None,
        description="Optional comma-separated entity IDs to include (bypasses updated_at ranking)",
    ),
    limit: int = Query(2000, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return a GeoJSON FeatureCollection of entities that have geometry.

    Entities without geometry are omitted.  Optional *type*, *bbox*, and *ids*
    filters narrow the result for map views.
    """
    conditions: list[str] = ["e.geometry IS NOT NULL"]
    args: list[Any] = []

    if type:
        args.append(type)
        conditions.append(f"e.type = ${len(args)}")

    if ids:
        id_list = [part.strip() for part in ids.split(",") if part.strip()]
        if id_list:
            args.append(id_list)
            conditions.append(f"e.id = ANY(${len(args)}::text[])")

    if bbox:
        parts = [p.strip() for p in bbox.split(",")]
        if len(parts) != 4:
            raise HTTPException(
                status_code=422,
                detail="bbox must be minLon,minLat,maxLon,maxLat",
            )
        try:
            min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="bbox values must be numeric",
            ) from exc
        args.extend([min_lon, min_lat, max_lon, max_lat])
        conditions.append(
            f"e.geometry && ST_MakeEnvelope("
            f"${len(args) - 3}, ${len(args) - 2}, ${len(args) - 1}, ${len(args)}, 4326)"
        )

    args.append(limit)
    where = " AND ".join(conditions)
    rows = await pool.fetch(
        f"""
        SELECT
            e.id,
            e.type,
            e.attributes,
            e.updated_at,
            ST_AsGeoJSON(e.geometry) AS geojson,
            s.status AS latest_status
        FROM entity e
        LEFT JOIN LATERAL (
            SELECT status
            FROM entity_state
            WHERE entity_id = e.id
            ORDER BY recorded_at DESC
            LIMIT 1
        ) s ON TRUE
        WHERE {where}
        ORDER BY e.updated_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )

    features: list[dict[str, Any]] = []
    for r in rows:
        if not r["geojson"]:
            continue
        attrs = json.loads(r["attributes"]) if r["attributes"] else {}
        features.append(
            {
                "type": "Feature",
                "id": r["id"],
                "geometry": json.loads(r["geojson"]),
                "properties": {
                    "id": r["id"],
                    "type": r["type"],
                    "status": r["latest_status"],
                    "attributes": attrs,
                    "updated_at": r["updated_at"].isoformat(),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    states_limit: int = Query(20, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return entity details plus its most-recent state history."""
    row = await pool.fetchrow(
        "SELECT id, type, attributes, created_at, updated_at "
        "FROM entity WHERE id = $1",
        entity_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    states = await pool.fetch(
        "SELECT status, recorded_at, attributes FROM entity_state "
        "WHERE entity_id = $1 ORDER BY recorded_at DESC LIMIT $2",
        entity_id,
        states_limit,
    )

    return {
        "id": row["id"],
        "type": row["type"],
        "attributes": json.loads(row["attributes"]) if row["attributes"] else {},
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "states": [
            {
                "status": s["status"],
                "recorded_at": s["recorded_at"].isoformat(),
                "attributes": json.loads(s["attributes"]) if s["attributes"] else {},
            }
            for s in states
        ],
    }


# ── Graph: nodes ──────────────────────────────────────────────────────────────

@router.get("/graph/nodes")
async def list_graph_nodes(
    limit: int = Query(100, ge=1, le=1000),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> list[dict[str, Any]]:
    """Return Entity nodes from the Neo4j graph with all properties."""
    async with neo4j_session(driver) as session:
        result = await session.run(
            "MATCH (n:Entity) RETURN properties(n) AS props LIMIT $limit",
            limit=limit,
        )
        records = await result.data()
    return [r["props"] for r in records if isinstance(r.get("props"), dict)]


# ── Graph: scenarios & events ─────────────────────────────────────────────────

@router.get("/graph/scenarios")
async def list_scenarios(
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> list[str]:
    """Return all distinct scenario IDs present in the Neo4j graph."""
    async with neo4j_session(driver) as session:
        result = await session.run(
            "MATCH (e:SimulationEvent) RETURN DISTINCT e.scenario_id AS sid"
        )
        records = await result.data()
    return [r["sid"] for r in records if r.get("sid") is not None]


@router.get("/graph/events")
async def list_graph_events(
    scenario_id: str | None = Query(None),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> list[dict[str, Any]]:
    """Return SimulationEvent nodes, optionally filtered by scenario_id."""
    async with neo4j_session(driver) as session:
        if scenario_id:
            result = await session.run(
                "MATCH (e:SimulationEvent {scenario_id: $sid}) "
                "RETURN properties(e) AS props",
                sid=scenario_id,
            )
        else:
            result = await session.run(
                "MATCH (e:SimulationEvent) RETURN properties(e) AS props LIMIT 200"
            )
        records = await result.data()
    return [r["props"] for r in records if isinstance(r.get("props"), dict)]


# ── Graph: edges ──────────────────────────────────────────────────────────────

@router.get("/graph/edges")
async def list_graph_edges(
    limit: int = Query(200, ge=1, le=2000),
    dependency_only: bool = Query(
        False,
        description="When true, omit simulation overlay edges (AFFECTED_BY).",
    ),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> list[dict[str, Any]]:
    """Return edges between graph nodes (dependency and/or simulation overlay)."""
    async with neo4j_session(driver) as session:
        if dependency_only:
            types = sorted(ALLOWED_DEPENDENCY_EDGE_TYPES)
            result = await session.run(
                "MATCH (a)-[r]->(b) "
                "WHERE type(r) IN $types "
                "RETURN a.id AS from_id, type(r) AS edge_type, b.id AS to_id "
                "LIMIT $limit",
                types=types,
                limit=limit,
            )
        else:
            result = await session.run(
                "MATCH (a)-[r]->(b) "
                "RETURN a.id AS from_id, type(r) AS edge_type, b.id AS to_id "
                "LIMIT $limit",
                limit=limit,
            )
        records = await result.data()
    return [
        {"from_id": r["from_id"], "edge_type": r["edge_type"], "to_id": r["to_id"]}
        for r in records
        if r.get("from_id") and r.get("edge_type") and r.get("to_id")
    ]


# ── Graph: inject / remove ────────────────────────────────────────────────────

class InjectEventRequest(BaseModel):
    id: str
    scenario_id: str
    description: str
    affected_entity_ids: list[str] = []
    bbox: str | None = None  # minLon,minLat,maxLon,maxLat — resolves from PostGIS
    attributes: dict[str, Any] = {}


@router.post("/graph/events", status_code=201)
async def inject_graph_event(
    body: InjectEventRequest,
    driver: AsyncDriver = Depends(get_neo4j_driver),
    pool: asyncpg.Pool = Depends(get_pool),
    llm_client: LLMClientBase = Depends(get_llm_client),
) -> dict[str, Any]:
    """Inject a simulation event overlay (additive — does not modify live data).

    Provide ``affected_entity_ids`` and/or ``bbox``.  When ``bbox`` is set,
    AFFECTED_BY edges are resolved from live PostGIS entities in that envelope
    and re-synced on every subsequent ``/query`` for the scenario.
    """
    from src.graph.spatial_overlay import (
        format_bbox,
        parse_bbox,
        sync_event_affected_from_bbox,
    )

    if not body.affected_entity_ids and not body.bbox:
        raise HTTPException(
            status_code=400,
            detail="Provide affected_entity_ids and/or bbox",
        )

    affect_bbox: str | None = None
    affected_ids = list(body.affected_entity_ids)

    if body.bbox:
        try:
            affect_bbox = format_bbox(parse_bbox(body.bbox))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    event = SimulationEvent(
        id=body.id,
        scenario_id=body.scenario_id,
        description=body.description,
        affected_entity_ids=affected_ids,
        affect_bbox=affect_bbox,
        attributes=body.attributes,
    )
    await inject_event(event, driver, llm_client)

    if affect_bbox:
        affected_ids = await sync_event_affected_from_bbox(
            driver, pool, event_id=body.id, bbox=affect_bbox
        )

    return {
        "status": "injected",
        "event_id": body.id,
        "affected_count": len(affected_ids),
        "affect_bbox": affect_bbox,
    }


@router.post("/graph/scenarios/{scenario_id}/sync-spatial")
async def sync_scenario_spatial(
    scenario_id: str,
    driver: AsyncDriver = Depends(get_neo4j_driver),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Refresh AFFECTED_BY edges from PostGIS for events with ``affect_bbox``."""
    from src.graph.spatial_overlay import refresh_scenario_spatial_overlays

    totals = await refresh_scenario_spatial_overlays(driver, pool, scenario_id)
    return {
        "status": "synced",
        "scenario_id": scenario_id,
        "events": totals,
        "total_affected": sum(totals.values()),
    }


@router.delete("/graph/scenarios/{scenario_id}", status_code=200)
async def delete_scenario(
    scenario_id: str,
    driver: AsyncDriver = Depends(get_neo4j_driver),
    llm_client: LLMClientBase = Depends(get_llm_client),
) -> dict[str, str]:
    """Remove all events for a scenario from both the graph and vector store."""
    await remove_scenario(scenario_id, driver, llm_client)
    return {"status": "removed", "scenario_id": scenario_id}


# ── Data sync & spatial helpers ───────────────────────────────────────────────


@router.get("/data/sync-status")
async def get_data_sync_status(
    pool: asyncpg.Pool = Depends(get_pool),
    driver: AsyncDriver = Depends(get_neo4j_driver),
    sample_limit: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    """Compare Entity IDs in Postgres vs Neo4j and report drift."""
    pg_rows = await pool.fetch("SELECT id FROM entity")
    postgres_ids = {r["id"] for r in pg_rows}

    async with neo4j_session(driver) as session:
        result = await session.run("MATCH (n:Entity) RETURN n.id AS id")
        records = await result.data()
    neo4j_ids = {r["id"] for r in records if r.get("id")}

    postgres_only = sorted(postgres_ids - neo4j_ids)
    neo4j_only = sorted(neo4j_ids - postgres_ids)

    return {
        "postgres_entity_count": len(postgres_ids),
        "neo4j_entity_count": len(neo4j_ids),
        "postgres_only_count": len(postgres_only),
        "neo4j_only_count": len(neo4j_only),
        "postgres_only_sample": postgres_only[:sample_limit],
        "neo4j_only_sample": neo4j_only[:sample_limit],
        "in_sync": not postgres_only and not neo4j_only,
    }


@router.get("/entities/in-bbox")
async def list_entity_ids_in_bbox(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat (WGS84)"),
    limit: int = Query(2000, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return entity IDs whose geometry intersects *bbox* in the live store."""
    try:
        parsed = parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = await list_entities_in_bbox(pool, parsed, limit=limit)
    ids = [r["id"] for r in rows if r.get("id")]
    return {
        "bbox": bbox,
        "count": len(ids),
        "entity_ids": ids,
    }


# ── Dependency edge editor ────────────────────────────────────────────────────


class DependencyEdgeBody(BaseModel):
    from_id: str
    to_id: str
    edge_type: str = EDGE_DEPENDS_ON


@router.post("/graph/dependency-edges", status_code=201)
async def create_graph_dependency_edge(
    body: DependencyEdgeBody,
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """MERGE a dependency edge between two Entity nodes (idempotent)."""
    if body.edge_type not in ALLOWED_DEPENDENCY_EDGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Unsupported edge type {body.edge_type!r}",
                "allowed": sorted(ALLOWED_DEPENDENCY_EDGE_TYPES),
            },
        )

    try:
        merged = await merge_dependency_edges(
            driver,
            [
                {
                    "from_id": body.from_id,
                    "to_id": body.to_id,
                    "edge_type": body.edge_type,
                }
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if merged == 0:
        # Nodes may be missing — attempt CREATE after explicit node check
        async with neo4j_session(driver) as session:
            check = await session.run(
                "MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id}) "
                "RETURN count(a) AS a_cnt, count(b) AS b_cnt",
                from_id=body.from_id,
                to_id=body.to_id,
            )
            record = await check.single()
        if not record or record["a_cnt"] == 0 or record["b_cnt"] == 0:
            raise HTTPException(
                status_code=404,
                detail="Both Entity nodes must exist in Neo4j before linking",
            )
        await create_dependency_edge(
            driver, body.from_id, body.to_id, edge_type=body.edge_type
        )
        merged = 1

    return {
        "status": "merged",
        "from_id": body.from_id,
        "to_id": body.to_id,
        "edge_type": body.edge_type,
        "edges_affected": merged,
    }


@router.delete("/graph/dependency-edges", status_code=200)
async def delete_graph_dependency_edge(
    from_id: str = Query(...),
    to_id: str = Query(...),
    edge_type: str = Query(EDGE_DEPENDS_ON),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """Remove a dependency edge (does not delete Entity nodes)."""
    try:
        deleted = await delete_dependency_edge(
            driver, from_id, to_id, edge_type=edge_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail="No matching dependency edge found",
        )
    return {
        "status": "deleted",
        "from_id": from_id,
        "to_id": to_id,
        "edge_type": edge_type,
        "edges_removed": deleted,
    }


# ── Ingestion operations ──────────────────────────────────────────────────────


@router.get("/ingestion/adapters")
async def list_ingestion_adapters() -> dict[str, Any]:
    """Return ingestion adapters available under ENABLED_DOMAINS."""
    settings = Settings()
    return {
        "enabled_domains": settings.parsed_enabled_domains,
        "adapters": list_adapter_catalog(settings),
    }


class IngestionRunBody(BaseModel):
    adapter_id: str


@router.post("/ingestion/run", status_code=200)
async def run_ingestion_adapter(
    body: IngestionRunBody,
    pool: asyncpg.Pool = Depends(get_pool),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """Run one on-demand ingestion cycle for *adapter_id*."""
    settings = Settings()
    try:
        adapter_cls = get_adapter_class(body.adapter_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    adapter = adapter_cls()
    try:
        count = await run_ingestion(adapter, pool, neo4j_driver=driver)
    except Exception as exc:
        logger.exception("Ingestion run failed: adapter=%s", body.adapter_id)
        raise HTTPException(
            status_code=500,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    return {
        "status": "completed",
        "adapter_id": body.adapter_id,
        "entities_upserted": count,
    }


# ── Platform operations ─────────────────────────────────────────────────────────


@router.get("/platform/config")
async def get_platform_config() -> dict[str, Any]:
    """Return read-only platform configuration (no secrets)."""
    settings = Settings()
    return {
        "enabled_domains": settings.parsed_enabled_domains,
        "llm_backend": settings.llm_backend,
        "generation_model_id": settings.generation_model_id,
        "embedding_model_id": settings.embedding_model_id,
        "embedding_dimension": settings.embedding_dimension,
        "postgres_host": _host_from_dsn(settings.postgres_dsn),
        "neo4j_uri": settings.neo4j_uri,
        "dependency_edge_types": sorted(ALLOWED_DEPENDENCY_EDGE_TYPES),
    }


def _host_from_dsn(dsn: str) -> str:
    """Extract host portion from a postgresql DSN for display."""
    try:
        # postgresql://user:pass@host:port/db
        without_scheme = dsn.split("://", 1)[-1]
        host_part = without_scheme.split("@", 1)[-1]
        return host_part.split("/", 1)[0]
    except Exception:
        return dsn


@router.post("/platform/bootstrap", status_code=200)
async def run_platform_bootstrap(
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, str]:
    """Run idempotent Postgres + Neo4j schema bootstrap."""
    settings = Settings()
    try:
        await bootstrap(settings.postgres_dsn, driver)
    except Exception as exc:
        logger.exception("Platform bootstrap failed")
        raise HTTPException(
            status_code=500,
            detail=f"Bootstrap failed: {exc}",
        ) from exc

    return {"status": "bootstrapped"}


# ── Graph file import (bring-your-own-graph) ──────────────────────────────────


class ImportMappingBody(BaseModel):
    format: str = "json"
    entity_id_column: str = "id"
    entity_type_column: str | None = "type"
    default_entity_type: str = "entity"
    status_column: str | None = "status"
    default_status: str = "imported"
    lon_column: str | None = "lon"
    lat_column: str | None = "lat"
    attribute_columns: list[str] = Field(default_factory=list)
    edge_from_column: str = "from_id"
    edge_to_column: str = "to_id"
    edge_type_column: str | None = "edge_type"
    default_edge_type: str = EDGE_DEPENDS_ON
    id_prefix: str = ""
    dataset_id: str | None = None


def _mapping_from_body(body: ImportMappingBody) -> ImportMapping:
    fmt = body.format.lower().strip()
    if fmt not in {"json", "csv"}:
        raise HTTPException(
            status_code=400,
            detail="format must be 'json' or 'csv'",
        )
    return ImportMapping(
        format=fmt,  # type: ignore[arg-type]
        entity_id_column=body.entity_id_column,
        entity_type_column=body.entity_type_column,
        default_entity_type=body.default_entity_type,
        status_column=body.status_column,
        default_status=body.default_status,
        lon_column=body.lon_column,
        lat_column=body.lat_column,
        attribute_columns=list(body.attribute_columns),
        edge_from_column=body.edge_from_column,
        edge_to_column=body.edge_to_column,
        edge_type_column=body.edge_type_column,
        default_edge_type=body.default_edge_type,
        id_prefix=body.id_prefix,
        dataset_id=body.dataset_id,
    )


async def _read_upload(upload: UploadFile | None, *, label: str) -> str | None:
    if upload is None:
        return None
    raw = await upload.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds {_MAX_UPLOAD_BYTES} bytes",
        )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be UTF-8 text",
        ) from exc


def _parse_mapping_form(mapping_json: str) -> ImportMapping:
    try:
        data = json.loads(mapping_json) if mapping_json.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid mapping JSON: {exc}"
        ) from exc
    body = ImportMappingBody.model_validate(data)
    return _mapping_from_body(body)


@router.get("/imports/formats")
async def import_formats() -> dict[str, Any]:
    """Return supported import formats and allowlisted edge types."""
    return {
        "formats": ["json", "csv"],
        "edge_types": sorted(ALLOWED_DEPENDENCY_EDGE_TYPES),
        "max_upload_bytes": _MAX_UPLOAD_BYTES,
    }


@router.post("/imports/preview")
async def preview_import(
    file: UploadFile = File(..., description="Entities JSON/CSV (or combined)"),
    edges_file: UploadFile | None = File(
        None, description="Optional separate edges CSV"
    ),
    mapping: str = Form(
        "{}",
        description="JSON ImportMapping (format, column names, …)",
    ),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """Parse and validate an upload without writing to the stores."""
    entities_text = await _read_upload(file, label="file")
    if not entities_text or not entities_text.strip():
        raise HTTPException(status_code=400, detail="file is empty")
    edges_text = await _read_upload(edges_file, label="edges_file")
    map_obj = _parse_mapping_form(mapping)

    draft = parse_import(
        entities_text=entities_text,
        mapping=map_obj,
        edges_text=edges_text,
    )
    await validate_draft(draft, neo4j_driver=driver)
    return draft_to_jsonable(draft)


@router.post("/imports/commit", status_code=201)
async def commit_graph_import(
    file: UploadFile = File(..., description="Entities JSON/CSV (or combined)"),
    edges_file: UploadFile | None = File(
        None, description="Optional separate edges CSV"
    ),
    mapping: str = Form(
        "{}",
        description="JSON ImportMapping (format, column names, …)",
    ),
    pool: asyncpg.Pool = Depends(get_pool),
    driver: AsyncDriver = Depends(get_neo4j_driver),
) -> dict[str, Any]:
    """Parse, validate, and upsert entities + MERGE dependency edges."""
    entities_text = await _read_upload(file, label="file")
    if not entities_text or not entities_text.strip():
        raise HTTPException(status_code=400, detail="file is empty")
    edges_text = await _read_upload(edges_file, label="edges_file")
    map_obj = _parse_mapping_form(mapping)

    draft = parse_import(
        entities_text=entities_text,
        mapping=map_obj,
        edges_text=edges_text,
    )
    await validate_draft(draft, neo4j_driver=driver)
    if not draft.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Import validation failed",
                "draft": draft_to_jsonable(draft),
            },
        )

    result = await commit_import(
        draft,
        pool=pool,
        neo4j_driver=driver,
        dataset_id=map_obj.dataset_id,
    )
    return {
        "status": "committed",
        "entities_upserted": result.entities_upserted,
        "edges_merged": result.edges_merged,
        "dataset_id": result.dataset_id,
        "draft": draft_to_jsonable(draft),
    }
