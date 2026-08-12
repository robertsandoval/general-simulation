"""Unit tests for bring-your-own-graph import (parse / validate / commit)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.graph.nodes import ALLOWED_DEPENDENCY_EDGE_TYPES, _require_allowed_edge_type
from src.importers.commit import commit_import, draft_to_jsonable
from src.importers.models import ImportDraft, ImportEdge, ImportEntity, ImportMapping
from src.importers.parse import detect_columns, parse_import
from src.importers.validate import validate_draft


def test_detect_columns_csv():
    text = "id,type,lon,lat\na,node,1,2\n"
    assert detect_columns(text, format="csv") == ["id", "type", "lon", "lat"]


def test_detect_columns_json_entities():
    text = '{"entities":[{"id":"n1","type":"node"}],"edges":[]}'
    assert "id" in detect_columns(text, format="json")


def test_parse_json_entities_and_edges():
    text = """
    {
      "entities": [
        {"id": "a", "type": "hub", "geometry": {"type": "Point", "coordinates": [0, 1]}},
        {"id": "b", "type": "link"}
      ],
      "edges": [
        {"from_id": "a", "to_id": "b", "edge_type": "DEPENDS_ON"}
      ]
    }
    """
    draft = parse_import(entities_text=text, mapping=ImportMapping(format="json"))
    assert len(draft.entities) == 2
    assert draft.entities[0].geometry["type"] == "Point"
    assert draft.entities[0].attributes.get("source") == "import"
    assert len(draft.edges) == 1
    assert draft.edges[0].edge_type == "DEPENDS_ON"


def test_parse_json_applies_id_prefix_and_dataset():
    text = '{"entities":[{"id":"1","type":"node"}],"edges":[]}'
    draft = parse_import(
        entities_text=text,
        mapping=ImportMapping(format="json", id_prefix="net-", dataset_id="demo"),
    )
    assert draft.entities[0].id == "net-1"
    assert draft.entities[0].attributes["dataset_id"] == "demo"


def test_parse_csv_nodes_and_separate_edges():
    nodes = "id,type,lon,lat,name\nn1,facility,-1.0,52.0,Hub\nn2,facility,-0.5,51.5,Spoke\n"
    edges = "from_id,to_id,edge_type\nn1,n2,FEEDS\n"
    draft = parse_import(
        entities_text=nodes,
        edges_text=edges,
        mapping=ImportMapping(format="csv"),
    )
    assert len(draft.entities) == 2
    assert draft.entities[0].geometry == {
        "type": "Point",
        "coordinates": [-1.0, 52.0],
    }
    assert draft.entities[0].attributes.get("name") == "Hub"
    assert len(draft.edges) == 1
    assert draft.edges[0].edge_type == "FEEDS"


def test_parse_csv_combined_row():
    text = "id,type,from_id,to_id,edge_type\na,node,a,b,CARRIES\nb,node,,,\n"
    draft = parse_import(entities_text=text, mapping=ImportMapping(format="csv"))
    assert {e.id for e in draft.entities} == {"a", "b"}
    assert len(draft.edges) == 1
    assert draft.edges[0].from_id == "a"
    assert draft.edges[0].to_id == "b"


@pytest.mark.asyncio
async def test_validate_rejects_bad_edge_type():
    draft = ImportDraft(
        entities=[ImportEntity(id="a", type="n"), ImportEntity(id="b", type="n")],
        edges=[ImportEdge(from_id="a", to_id="b", edge_type="HACKS")],
    )
    await validate_draft(draft)
    assert draft.error_count >= 1
    assert any("not allowed" in i.message for i in draft.issues)


@pytest.mark.asyncio
async def test_validate_rejects_missing_endpoint():
    draft = ImportDraft(
        entities=[ImportEntity(id="a", type="n")],
        edges=[ImportEdge(from_id="a", to_id="missing", edge_type="DEPENDS_ON")],
    )
    await validate_draft(draft, neo4j_driver=None)
    assert any("not found" in i.message for i in draft.issues)
    assert not draft.ok


@pytest.mark.asyncio
async def test_validate_ok_when_complete():
    draft = ImportDraft(
        entities=[ImportEntity(id="a", type="n"), ImportEntity(id="b", type="n")],
        edges=[ImportEdge(from_id="a", to_id="b", edge_type="DEPENDS_ON")],
    )
    await validate_draft(draft)
    assert draft.ok
    assert draft.error_count == 0


def test_require_allowed_edge_type():
    assert _require_allowed_edge_type("DEPENDS_ON") == "DEPENDS_ON"
    with pytest.raises(ValueError):
        _require_allowed_edge_type("DROP")
    assert "CARRIES" in ALLOWED_DEPENDENCY_EDGE_TYPES


def test_draft_to_jsonable():
    draft = ImportDraft(
        entities=[ImportEntity(id="a", type="n")],
        edges=[ImportEdge(from_id="a", to_id="a", edge_type="DEPENDS_ON")],
    )
    payload = draft_to_jsonable(draft)
    assert payload["entity_count"] == 1
    assert payload["edge_count"] == 1
    assert payload["entities"][0]["id"] == "a"


@pytest.mark.asyncio
async def test_commit_import_calls_upserts():
    draft = ImportDraft(
        entities=[
            ImportEntity(id="a", type="hub", attributes={"source": "import"}),
            ImportEntity(id="b", type="link", attributes={"source": "import"}),
        ],
        edges=[ImportEdge(from_id="a", to_id="b", edge_type="DEPENDS_ON")],
    )
    await validate_draft(draft)
    assert draft.ok

    conn = AsyncMock()
    # asyncpg: conn.transaction() returns an async context manager (not a coroutine)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    driver = MagicMock()

    with (
        patch("src.importers.commit._upsert_entity", new_callable=AsyncMock) as up,
        patch("src.importers.commit._insert_state", new_callable=AsyncMock) as st,
        patch(
            "src.importers.commit.merge_entity_nodes", new_callable=AsyncMock
        ) as merge_n,
        patch(
            "src.importers.commit.merge_dependency_edges", new_callable=AsyncMock
        ) as merge_e,
    ):
        merge_n.return_value = 2
        merge_e.return_value = 1
        result = await commit_import(
            draft, pool=pool, neo4j_driver=driver, dataset_id="demo"
        )

    assert result.entities_upserted == 2
    assert result.edges_merged == 1
    assert up.await_count == 2
    assert st.await_count == 2
    merge_n.assert_awaited_once()
    merge_e.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_rejects_invalid_draft():
    draft = ImportDraft()
    await validate_draft(draft)
    with pytest.raises(ValueError):
        await commit_import(draft, pool=MagicMock(), neo4j_driver=MagicMock())
