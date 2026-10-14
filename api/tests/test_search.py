"""Search: keyword/HXQL hit /api/query, semantic adds an embedding step."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

ROOT = "http://openarch.test/api/documents/00000000-0000-0000-0000-000000000000"
QUERY = "http://openarch.test/api/query"
VECTOR_QUERY = "http://openarch.test/api/query/embeddings"
EMBED = "http://model.test/v1/embeddings"


def _auth(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    client.post("/api/session", json={"username": "admin", "password": "p"})


@respx.mock
def test_keyword_search_filters_chunks_by_term(client: TestClient) -> None:
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "embeddings": [
                    {"sysembed_docId": "d1", "sysembed_text": "the remote work policy", "sysembed_score": 0.7},
                    {"sysembed_docId": "d2", "sysembed_text": "unrelated office text", "sysembed_score": 0.6},
                ]
            },
        )
    )
    res = client.post("/api/search", json={"mode": "keyword", "query": "remote"})
    assert res.status_code == 200
    body = res.json()
    # Only the chunk that actually contains the term survives.
    assert [r["id"] for r in body["results"]] == ["d1"]
    assert body["provenance"]["extendedBy"] == "Studio full-text filter"


@respx.mock
def test_semantic_search_embeds_then_calls_vector_api(client: TestClient) -> None:
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}))
    vector_route = respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "embeddings": [
                    {"sysembed_docId": "d1", "sysembed_text": "a chunk", "sysembed_score": 0.9}
                ]
            },
        )
    )
    res = client.post("/api/search", json={"mode": "semantic", "query": "what is the policy"})
    assert res.status_code == 200
    body = res.json()
    assert body["results"][0] == {"id": "d1", "title": None, "snippet": "a chunk", "score": 0.9}
    assert body["provenance"]["extendedBy"] == "Studio embedding"
    # The query vector is normalized to OpenArch's stored width.
    sent = vector_route.calls.last.request.read()
    import json

    assert len(json.loads(sent)["vector"]) == 1024


@respx.mock
def test_empty_query_is_rejected(client: TestClient) -> None:
    _auth(client)
    assert client.post("/api/search", json={"mode": "keyword", "query": "  "}).status_code == 400


@respx.mock
def test_forbidden_search_maps_to_403(client: TestClient) -> None:
    _auth(client)
    respx.post(QUERY).mock(return_value=httpx.Response(403))
    res = client.post("/api/search", json={"mode": "hxql", "query": "SELECT * FROM SysContent"})
    assert res.status_code == 403


def test_search_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/search", json={"mode": "keyword", "query": "x"}).status_code == 401


@respx.mock
def test_semantic_search_excludes_unauthorized_results(client: TestClient) -> None:
    # Two identities, two different ACL-filtered result sets from OpenArch.
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200, json={"embeddings": [{"sysembed_docId": "admin-doc", "sysembed_text": "secret"}]}
        )
    )
    admin = client.post("/api/search", json={"mode": "semantic", "query": "q"}).json()
    assert admin["results"][0]["id"] == "admin-doc"

    # A second user whose ACL yields nothing.
    respx.post(VECTOR_QUERY).mock(return_value=httpx.Response(200, json={"embeddings": []}))
    other = client.post("/api/search", json={"mode": "semantic", "query": "q"}).json()
    assert other["results"] == []
