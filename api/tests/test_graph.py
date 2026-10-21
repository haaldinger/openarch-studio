"""Knowledge graph: parsing, permission-filtered merge, extraction endpoint."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import DocGraph, GraphService, parse_graph
from app.models import Credentials

OA = "http://openarch.test"
CHAT = "http://model.test/v1/chat/completions"
ROOT = f"{OA}/api/documents/00000000-0000-0000-0000-000000000000"


def make_service() -> GraphService:
    return GraphService(
        Settings(openarch_url=OA, model_base_url="http://model.test/v1", chat_model="llama3.2:1b")
    )


def test_parse_graph_tolerates_fences_and_drops_bad_types() -> None:
    raw = """```json
    {"entities":[{"name":"Acme","type":"Organization"},
                 {"name":"Bob","type":"Alien"}],
     "relations":[{"source":"Acme","target":"Bob","type":"employs"}]}
    ```"""
    g = parse_graph(raw)
    # Bad-typed entity dropped; its dangling relation dropped too.
    assert set(g.entities) == {"acme"}
    assert g.relations == []


def test_parse_graph_keeps_valid_relations() -> None:
    raw = (
        '{"entities":[{"name":"Acme","type":"Organization"},'
        '{"name":"Remote Policy","type":"Policy"}],'
        '"relations":[{"source":"Acme","target":"Remote Policy","type":"has"}]}'
    )
    g = parse_graph(raw)
    assert set(g.entities) == {"acme", "remote policy"}
    assert g.relations == [("acme", "remote policy", "has")]


def test_parse_graph_recovers_edges_from_name_variants() -> None:
    # The model names the endpoint "Acme" but the entity is "Acme Corporation".
    raw = (
        '{"entities":[{"name":"Acme Corporation","type":"Organization"},'
        '{"name":"Berlin","type":"Location"}],'
        '"relations":[{"source":"Acme","target":"Berlin","type":"located in"}]}'
    )
    g = parse_graph(raw)
    assert g.relations == [("acme", "berlin", "located in")]


def test_legal_suffix_and_case_variants_are_one_entity() -> None:
    raw = (
        '{"entities":[{"name":"HYLAND SOFTWARE","type":"Organization"},'
        '{"name":"Hyland Software, Inc.","type":"Organization"}],"relations":[]}'
    )
    assert set(parse_graph(raw).entities) == {"hyland software"}


def test_distinct_organizations_are_not_merged() -> None:
    raw = (
        '{"entities":[{"name":"Hyland Software","type":"Organization"},'
        '{"name":"International Software","type":"Organization"}],"relations":[]}'
    )
    assert len(parse_graph(raw).entities) == 2


@respx.mock
async def test_extract_calls_model_and_stores() -> None:
    respx.post(CHAT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"entities":[{"name":"Acme","type":"Organization"}],"relations":[]}'
                        }
                    }
                ]
            },
        )
    )
    service = make_service()
    graph = await service.extract("d1", "Acme Corporation policy text")
    assert "acme" in graph.entities
    assert service.store.get("d1") is not None


@respx.mock
async def test_merged_excludes_unreadable_documents() -> None:
    service = make_service()
    # Seed two docs directly in the store.
    respx.post(CHAT).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"entities":[{"name":"Acme","type":"Organization"}],"relations":[]}'}}]},
        )
    )
    await service.extract("ok", "Acme")
    await service.extract("secret", "Acme")

    respx.get(f"{OA}/api/documents/ok").mock(return_value=httpx.Response(200, json={"sys_id": "ok"}))
    respx.get(f"{OA}/api/documents/secret").mock(return_value=httpx.Response(403))

    merged = await service.merged(Credentials(username="u", password="p"))
    # The node survives (from 'ok'), but it is not attributed to the forbidden doc.
    node = next(n for n in merged["nodes"] if n["label"] == "Acme")
    assert node["docIds"] == ["ok"]


@respx.mock
async def test_merged_collapses_name_variants_across_documents() -> None:
    """Graphs stored before canonicalization existed must still de-duplicate."""
    service = make_service()
    service.store.put(
        "d1",
        DocGraph(entities={"hyland software": {"label": "HYLAND SOFTWARE", "type": "Organization"}}),
    )
    service.store.put(
        "d2",
        DocGraph(
            entities={
                "hyland software, inc.": {"label": "Hyland Software, Inc.", "type": "Organization"}
            }
        ),
    )
    for doc_id in ("d1", "d2"):
        respx.get(f"{OA}/api/documents/{doc_id}").mock(
            return_value=httpx.Response(200, json={"sys_id": doc_id})
        )

    merged = await service.merged(Credentials(username="u", password="p"))
    assert len(merged["nodes"]) == 1
    node = merged["nodes"][0]
    # Both documents are credited, and the readable label wins over OCR'd caps.
    assert sorted(node["docIds"]) == ["d1", "d2"]
    assert node["label"] == "Hyland Software, Inc."


@respx.mock
def test_graph_endpoint_requires_auth(client: TestClient) -> None:
    assert client.get("/api/graph").status_code == 401
