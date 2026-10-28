"""Search: keyword/HXQL hit /api/query, semantic adds an embedding step."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ROOT = "http://openarch.test/api/documents/00000000-0000-0000-0000-000000000000"
QUERY = "http://openarch.test/api/query"
VECTOR_QUERY = "http://openarch.test/api/query/embeddings"
EMBED = "http://model.test/v1/embeddings"
RERANK = "http://reranker.test/rerank"


def _auth(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    client.post("/api/session", json={"username": "admin", "password": "p"})


@respx.mock
def test_keyword_search_filters_chunks_by_term(client: TestClient) -> None:
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
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
def test_keyword_search_limit_not_capped_without_reranker(client: TestClient) -> None:
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    hits = [{"sysembed_docId": f"d{i}", "sysembed_text": "remote", "sysembed_score": 0.5} for i in range(25)]
    respx.post(VECTOR_QUERY).mock(return_value=httpx.Response(200, json={"embeddings": hits}))
    body = client.post("/api/search", json={"mode": "keyword", "query": "remote", "limit": 20}).json()
    assert len(body["results"]) == 20


@respx.mock
def test_semantic_search_embeds_then_calls_vector_api(client: TestClient) -> None:
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    vector_route = respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "embeddings": [
                    {
                        "sysembed_docId": "d1",
                        "sysembed_text": "a chunk",
                        "sysembed_score": 0.9,
                        "sysembed_location": {"text": {"page": 2, "paragraph": 1}},
                    }
                ]
            },
        )
    )
    res = client.post("/api/search", json={"mode": "semantic", "query": "what is the policy"})
    assert res.status_code == 200
    body = res.json()
    assert body["results"][0] == {
        "id": "d1", "title": None, "snippet": "a chunk", "score": 0.9, "vectorScore": 0.9, "page": 2
    }
    assert body["provenance"]["extendedBy"] == "Studio embedding"
    assert body["provenance"]["rerank"] == "skipped (not configured)"
    # The query vector is normalized to OpenArch's stored width.
    sent = vector_route.calls.last.request.read()
    assert len(json.loads(sent)["vector"]) == 1024


def _rerank_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(
                openarch_url="http://openarch.test",
                tika_url="http://tika.test",
                model_base_url="http://model.test/v1",
                reranker_url="http://reranker.test",
            )
        )
    )


def _two_hits() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "embeddings": [
                {"sysembed_docId": "d1", "sysembed_text": "remote one", "sysembed_score": 0.9},
                {"sysembed_docId": "d2", "sysembed_text": "remote two", "sysembed_score": 0.8},
            ]
        },
    )


@respx.mock
def test_semantic_search_reports_rerank_status() -> None:
    client = _rerank_client()
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    vector_route = respx.post(VECTOR_QUERY).mock(return_value=_two_hits())
    respx.post(RERANK).mock(
        return_value=httpx.Response(200, json=[{"index": 1, "score": 0.95}, {"index": 0, "score": 0.1}])
    )
    body = client.post("/api/search", json={"mode": "semantic", "query": "q", "limit": 1}).json()
    assert json.loads(vector_route.calls.last.request.read())["limit"] == 2
    assert body["provenance"]["rerank"] == "reranked"
    [top] = body["results"]
    assert (top["id"], top["score"], top["vectorScore"]) == ("d2", 0.95, 0.8)


@respx.mock
def test_keyword_search_reranks_filtered_hits() -> None:
    client = _rerank_client()
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    respx.post(VECTOR_QUERY).mock(return_value=_two_hits())
    respx.post(RERANK).mock(
        return_value=httpx.Response(200, json=[{"index": 1, "score": 0.95}, {"index": 0, "score": 0.1}])
    )
    body = client.post("/api/search", json={"mode": "keyword", "query": "remote"}).json()
    assert [r["id"] for r in body["results"]] == ["d2", "d1"]
    assert body["provenance"]["rerank"] == "reranked"


@respx.mock
def test_reranker_down_keeps_vector_order() -> None:
    client = _rerank_client()
    _auth(client)
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    respx.post(VECTOR_QUERY).mock(return_value=_two_hits())
    respx.post(RERANK).mock(return_value=httpx.Response(503))
    body = client.post("/api/search", json={"mode": "semantic", "query": "q"}).json()
    assert body["provenance"]["rerank"].startswith("skipped")
    assert [(r["id"], r["score"]) for r in body["results"]] == [("d1", 0.9), ("d2", 0.8)]


@respx.mock
def test_hxql_search_is_not_reranked(client: TestClient) -> None:
    _auth(client)
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    body = client.post("/api/search", json={"mode": "hxql", "query": "select"}).json()
    assert body["provenance"]["rerank"] is None


@respx.mock
def test_baseline_mode_never_reaches_reranker() -> None:
    client = TestClient(
        create_app(
            Settings(
                openarch_url="http://openarch.test",
                model_base_url="http://model.test/v1",
                reranker_url="http://reranker.test",
                baseline_mode=True,
            )
        )
    )
    rerank_route = respx.post(RERANK).mock(return_value=httpx.Response(200, json=[]))
    assert client.post("/api/search", json={"mode": "semantic", "query": "q"}).status_code == 403
    assert not rerank_route.called


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
    respx.post(QUERY).mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "admin-doc"}]}))
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
