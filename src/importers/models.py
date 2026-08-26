"""Domain-agnostic shapes for graph file import."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.graph.nodes import ALLOWED_DEPENDENCY_EDGE_TYPES, EDGE_DEPENDS_ON

ALLOWED_EDGE_TYPES: frozenset[str] = ALLOWED_DEPENDENCY_EDGE_TYPES

ImportFormat = Literal["json", "csv"]


@dataclass
class ImportMapping:
    """How to interpret an uploaded file as entities and/or edges.

    For ``json`` format the payload is expected to already match the import
    model (``entities`` / ``edges`` arrays); column fields are ignored unless
    the JSON is a flat list of objects treated like CSV rows.

    For ``csv``:
      - ``entities_text`` uses the entity_* / attribute column mappings.
      - ``edges_text`` (optional second file) uses the edge_* mappings.
      - A single CSV may also contain edge columns; rows with both entity id
        and from/to produce an entity *and* an edge.
    """

    format: ImportFormat = "json"
    entity_id_column: str = "id"
    entity_type_column: str | None = "type"
    default_entity_type: str = "entity"
    status_column: str | None = "status"
    default_status: str = "imported"
    lon_column: str | None = "lon"
    lat_column: str | None = "lat"
    attribute_columns: list[str] = field(default_factory=list)
    edge_from_column: str = "from_id"
    edge_to_column: str = "to_id"
    edge_type_column: str | None = "edge_type"
    default_edge_type: str = EDGE_DEPENDS_ON
    id_prefix: str = ""
    dataset_id: str | None = None


@dataclass
class ImportEntity:
    id: str
    type: str
    status: str = "imported"
    geometry: dict[str, Any] | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportEdge:
    from_id: str
    to_id: str
    edge_type: str = EDGE_DEPENDS_ON


@dataclass
class ImportIssue:
    level: Literal["error", "warning"]
    message: str
    row: int | None = None


@dataclass
class ImportDraft:
    entities: list[ImportEntity] = field(default_factory=list)
    edges: list[ImportEdge] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)
    detected_columns: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    @property
    def ok(self) -> bool:
        return self.error_count == 0 and (bool(self.entities) or bool(self.edges))


@dataclass
class ImportResult:
    entities_upserted: int
    edges_merged: int
    dataset_id: str | None = None
