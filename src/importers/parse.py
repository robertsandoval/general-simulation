"""Parse CSV / JSON uploads into an ImportDraft (pre-validation)."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from src.importers.models import (
    ImportDraft,
    ImportEdge,
    ImportEntity,
    ImportIssue,
    ImportMapping,
)

# Soft caps — hard failures happen in validate.
_MAX_ENTITY_ROWS = 10_000
_MAX_EDGE_ROWS = 50_000


def detect_columns(text: str, format: str = "csv") -> list[str]:
    """Return header / key names from a sample payload (for UI mapping)."""
    fmt = format.lower().strip()
    if fmt == "json":
        data = json.loads(text)
        if isinstance(data, dict):
            entities = data.get("entities")
            if isinstance(entities, list) and entities and isinstance(entities[0], dict):
                return sorted(entities[0].keys())
            edges = data.get("edges")
            if isinstance(edges, list) and edges and isinstance(edges[0], dict):
                return sorted(edges[0].keys())
            return sorted(data.keys())
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return sorted(data[0].keys())
        return []

    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or [])


def parse_import(
    *,
    entities_text: str,
    mapping: ImportMapping,
    edges_text: str | None = None,
) -> ImportDraft:
    """Parse file text into entities/edges; collect parse-level issues."""
    draft = ImportDraft()
    fmt = mapping.format

    try:
        draft.detected_columns = detect_columns(entities_text, format=fmt)
    except (json.JSONDecodeError, csv.Error) as exc:
        draft.issues.append(
            ImportIssue(level="error", message=f"Failed to read headers: {exc}")
        )
        return draft

    if fmt == "json":
        _parse_json(entities_text, mapping, draft)
    elif fmt == "csv":
        _parse_csv_entities(entities_text, mapping, draft)
        if edges_text:
            _parse_csv_edges(edges_text, mapping, draft)
    else:
        draft.issues.append(
            ImportIssue(level="error", message=f"Unsupported format: {fmt!r}")
        )

    return draft


def _apply_prefix(raw_id: str, mapping: ImportMapping) -> str:
    prefix = mapping.id_prefix or ""
    if not prefix:
        return raw_id
    if raw_id.startswith(prefix):
        return raw_id
    return f"{prefix}{raw_id}"


def _point_geometry(lon: Any, lat: Any) -> dict[str, Any] | None:
    if lon in (None, "") or lat in (None, ""):
        return None
    try:
        return {
            "type": "Point",
            "coordinates": [float(lon), float(lat)],
        }
    except (TypeError, ValueError):
        return None


def _coerce_attr(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool, dict, list)):
        return value
    text = str(value).strip()
    if text == "":
        return ""
    lower = text.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _entity_from_row(
    row: dict[str, Any],
    mapping: ImportMapping,
    row_num: int,
    draft: ImportDraft,
) -> ImportEntity | None:
    raw_id = row.get(mapping.entity_id_column)
    if raw_id is None or str(raw_id).strip() == "":
        return None

    entity_id = _apply_prefix(str(raw_id).strip(), mapping)

    if mapping.entity_type_column and row.get(mapping.entity_type_column) not in (
        None,
        "",
    ):
        entity_type = str(row[mapping.entity_type_column]).strip()
    else:
        entity_type = mapping.default_entity_type

    if mapping.status_column and row.get(mapping.status_column) not in (None, ""):
        status = str(row[mapping.status_column]).strip()
    else:
        status = mapping.default_status

    lon = row.get(mapping.lon_column) if mapping.lon_column else None
    lat = row.get(mapping.lat_column) if mapping.lat_column else None
    geometry = _point_geometry(lon, lat)
    if mapping.lon_column and mapping.lat_column:
        if (lon not in (None, "") or lat not in (None, "")) and geometry is None:
            draft.issues.append(
                ImportIssue(
                    level="warning",
                    message=f"Invalid lon/lat for entity {entity_id!r}",
                    row=row_num,
                )
            )

    skip_keys = {
        mapping.entity_id_column,
        mapping.entity_type_column,
        mapping.status_column,
        mapping.lon_column,
        mapping.lat_column,
        mapping.edge_from_column,
        mapping.edge_to_column,
        mapping.edge_type_column,
    }
    skip_keys.discard(None)

    attributes: dict[str, Any] = {}
    if mapping.attribute_columns:
        for col in mapping.attribute_columns:
            if col in row and col not in skip_keys:
                attributes[col] = _coerce_attr(row[col])
    else:
        for key, value in row.items():
            if key in skip_keys:
                continue
            if key in {
                "geometry",
                "from_id",
                "to_id",
                "edge_type",
                "attributes",
            }:
                continue
            attributes[key] = _coerce_attr(value)

    if mapping.dataset_id:
        attributes.setdefault("dataset_id", mapping.dataset_id)
    attributes.setdefault("source", "import")

    # Explicit GeoJSON geometry on the row wins over lon/lat.
    raw_geom = row.get("geometry")
    if isinstance(raw_geom, dict) and raw_geom.get("type"):
        geometry = raw_geom
    elif isinstance(raw_geom, str) and raw_geom.strip().startswith("{"):
        try:
            parsed = json.loads(raw_geom)
            if isinstance(parsed, dict) and parsed.get("type"):
                geometry = parsed
        except json.JSONDecodeError:
            draft.issues.append(
                ImportIssue(
                    level="warning",
                    message=f"Unparseable geometry JSON for {entity_id!r}",
                    row=row_num,
                )
            )

    return ImportEntity(
        id=entity_id,
        type=entity_type,
        status=status,
        geometry=geometry,
        attributes=attributes,
    )


def _edge_from_row(
    row: dict[str, Any],
    mapping: ImportMapping,
    row_num: int,
    draft: ImportDraft,
) -> ImportEdge | None:
    raw_from = row.get(mapping.edge_from_column)
    raw_to = row.get(mapping.edge_to_column)
    if raw_from in (None, "") or raw_to in (None, ""):
        return None

    from_id = _apply_prefix(str(raw_from).strip(), mapping)
    to_id = _apply_prefix(str(raw_to).strip(), mapping)

    if mapping.edge_type_column and row.get(mapping.edge_type_column) not in (
        None,
        "",
    ):
        edge_type = str(row[mapping.edge_type_column]).strip().upper()
    else:
        edge_type = mapping.default_edge_type.strip().upper()

    if not edge_type:
        draft.issues.append(
            ImportIssue(
                level="error",
                message="Empty edge_type",
                row=row_num,
            )
        )
        return None

    return ImportEdge(from_id=from_id, to_id=to_id, edge_type=edge_type)


def _parse_json(text: str, mapping: ImportMapping, draft: ImportDraft) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        draft.issues.append(
            ImportIssue(level="error", message=f"Invalid JSON: {exc}")
        )
        return

    if isinstance(data, dict) and (
        "entities" in data or "edges" in data
    ):
        entities_raw = data.get("entities") or []
        edges_raw = data.get("edges") or []
        if not isinstance(entities_raw, list) or not isinstance(edges_raw, list):
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message="JSON 'entities' and 'edges' must be arrays",
                )
            )
            return
        for i, item in enumerate(entities_raw, start=1):
            if not isinstance(item, dict):
                draft.issues.append(
                    ImportIssue(
                        level="error",
                        message="Entity entry must be an object",
                        row=i,
                    )
                )
                continue
            # Prefer explicit import-model fields; fall back to column mapping.
            if "id" in item:
                entity = _entity_from_explicit(item, mapping, i, draft)
            else:
                entity = _entity_from_row(item, mapping, i, draft)
            if entity:
                draft.entities.append(entity)
            if len(draft.entities) > _MAX_ENTITY_ROWS:
                draft.issues.append(
                    ImportIssue(
                        level="error",
                        message=f"Too many entities (max {_MAX_ENTITY_ROWS})",
                    )
                )
                return
        for i, item in enumerate(edges_raw, start=1):
            if not isinstance(item, dict):
                draft.issues.append(
                    ImportIssue(
                        level="error",
                        message="Edge entry must be an object",
                        row=i,
                    )
                )
                continue
            edge = _edge_from_explicit(item, mapping, i, draft)
            if edge:
                draft.edges.append(edge)
            if len(draft.edges) > _MAX_EDGE_ROWS:
                draft.issues.append(
                    ImportIssue(
                        level="error",
                        message=f"Too many edges (max {_MAX_EDGE_ROWS})",
                    )
                )
                return
        return

    if isinstance(data, list):
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                draft.issues.append(
                    ImportIssue(
                        level="error",
                        message="List items must be objects",
                        row=i,
                    )
                )
                continue
            entity = _entity_from_row(item, mapping, i, draft)
            if entity:
                draft.entities.append(entity)
            edge = _edge_from_row(item, mapping, i, draft)
            if edge:
                draft.edges.append(edge)
        return

    draft.issues.append(
        ImportIssue(
            level="error",
            message=(
                "JSON must be {entities, edges} object or an array of row objects"
            ),
        )
    )


def _entity_from_explicit(
    item: dict[str, Any],
    mapping: ImportMapping,
    row_num: int,
    draft: ImportDraft,
) -> ImportEntity | None:
    raw_id = item.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        draft.issues.append(
            ImportIssue(level="error", message="Entity missing id", row=row_num)
        )
        return None

    entity_id = _apply_prefix(str(raw_id).strip(), mapping)
    entity_type = str(item.get("type") or mapping.default_entity_type).strip()
    status = str(item.get("status") or mapping.default_status).strip()
    geometry = item.get("geometry")
    if geometry is not None and not (
        isinstance(geometry, dict) and geometry.get("type")
    ):
        draft.issues.append(
            ImportIssue(
                level="warning",
                message=f"Ignoring invalid geometry on {entity_id!r}",
                row=row_num,
            )
        )
        geometry = None

    attributes = item.get("attributes")
    if attributes is None:
        attributes = {}
    if not isinstance(attributes, dict):
        draft.issues.append(
            ImportIssue(
                level="error",
                message=f"attributes must be an object on {entity_id!r}",
                row=row_num,
            )
        )
        return None

    attrs = dict(attributes)
    if mapping.dataset_id:
        attrs.setdefault("dataset_id", mapping.dataset_id)
    attrs.setdefault("source", "import")

    return ImportEntity(
        id=entity_id,
        type=entity_type,
        status=status,
        geometry=geometry if isinstance(geometry, dict) else None,
        attributes=attrs,
    )


def _edge_from_explicit(
    item: dict[str, Any],
    mapping: ImportMapping,
    row_num: int,
    draft: ImportDraft,
) -> ImportEdge | None:
    raw_from = item.get("from_id")
    raw_to = item.get("to_id")
    if raw_from in (None, "") or raw_to in (None, ""):
        draft.issues.append(
            ImportIssue(
                level="error",
                message="Edge missing from_id or to_id",
                row=row_num,
            )
        )
        return None

    edge_type = str(
        item.get("edge_type") or mapping.default_edge_type
    ).strip().upper()
    return ImportEdge(
        from_id=_apply_prefix(str(raw_from).strip(), mapping),
        to_id=_apply_prefix(str(raw_to).strip(), mapping),
        edge_type=edge_type,
    )


def _parse_csv_entities(
    text: str, mapping: ImportMapping, draft: ImportDraft
) -> None:
    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        draft.issues.append(
            ImportIssue(level="error", message=f"Invalid CSV: {exc}")
        )
        return

    if not reader.fieldnames:
        draft.issues.append(
            ImportIssue(level="error", message="CSV has no header row")
        )
        return

    for i, row in enumerate(reader, start=2):  # header is row 1
        entity = _entity_from_row(row, mapping, i, draft)
        if entity:
            draft.entities.append(entity)
        # Allow a combined nodes+edges CSV.
        edge = _edge_from_row(row, mapping, i, draft)
        if edge:
            draft.edges.append(edge)
        if len(draft.entities) > _MAX_ENTITY_ROWS:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Too many entities (max {_MAX_ENTITY_ROWS})",
                )
            )
            return
        if len(draft.edges) > _MAX_EDGE_ROWS:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Too many edges (max {_MAX_EDGE_ROWS})",
                )
            )
            return


def _parse_csv_edges(text: str, mapping: ImportMapping, draft: ImportDraft) -> None:
    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        draft.issues.append(
            ImportIssue(level="error", message=f"Invalid edges CSV: {exc}")
        )
        return

    if not reader.fieldnames:
        draft.issues.append(
            ImportIssue(level="error", message="Edges CSV has no header row")
        )
        return

    for i, row in enumerate(reader, start=2):
        edge = _edge_from_row(row, mapping, i, draft)
        if edge is None:
            draft.issues.append(
                ImportIssue(
                    level="warning",
                    message="Skipping edges row without from/to",
                    row=i,
                )
            )
            continue
        draft.edges.append(edge)
        if len(draft.edges) > _MAX_EDGE_ROWS:
            draft.issues.append(
                ImportIssue(
                    level="error",
                    message=f"Too many edges (max {_MAX_EDGE_ROWS})",
                )
            )
            return
