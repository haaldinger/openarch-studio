"""Reranker client: cross-encoder ordering with vector-order fallback."""

from __future__ import annotations

import json

import httpx
import respx

from app.config import Settings
from app.rerank import Reranker

URL = "http://reranker.test/rerank"


def make_reranker(url: str = "http://reranker.test") -> Reranker:
    return Reranker(
        Settings(
            openarch_url="http://openarch.test",
            tika_url="http://tika.test",
            model_base_url="http://model.test/v1",
            reranker_url=url,
        )
    )


@respx.mock
async def test_reorders_by_score():
    respx.post(URL).respond(json=[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}])
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "reranked"
    assert outcome.order == [1, 0]
    assert outcome.scores == [0.1, 0.9]


@respx.mock
async def test_unset_url_skips():
    route = respx.post(URL).respond(json=[])
    outcome = await make_reranker("").rerank("q", ["a", "b", "c"])
    assert outcome.status == "skipped (not configured)"
    assert outcome.order == [0, 1, 2]
    assert outcome.scores == [None, None, None]
    assert not route.called


@respx.mock
async def test_timeout_skips():
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "skipped (timeout)"
    assert outcome.order == [0, 1]
    assert outcome.scores == [None, None]


@respx.mock
async def test_5xx_skips():
    respx.post(URL).respond(503)
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "skipped (HTTP 503)"
    assert outcome.order == [0, 1]


@respx.mock
async def test_missing_index_falls_back():
    respx.post(URL).respond(json=[{"index": 2, "score": 0.9}, {"index": 0, "score": 0.1}])
    outcome = await make_reranker().rerank("q", ["a", "b", "c"])
    assert outcome.status == "skipped (incomplete response)"
    assert outcome.order == [0, 1, 2]
    assert outcome.scores == [None, None, None]


@respx.mock
async def test_unreachable_skips():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "skipped (unreachable)"
    assert outcome.order == [0, 1]


@respx.mock
async def test_malformed_json_falls_back():
    respx.post(URL).respond(content=b"not json")
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "skipped (incomplete response)"
    assert outcome.order == [0, 1]


@respx.mock
async def test_out_of_range_index_falls_back():
    respx.post(URL).respond(json=[{"index": 5, "score": 0.9}, {"index": 0, "score": 0.1}])
    outcome = await make_reranker().rerank("q", ["a", "b"])
    assert outcome.status == "skipped (incomplete response)"
    assert outcome.order == [0, 1]
    assert outcome.scores == [None, None]


@respx.mock
async def test_empty_texts_make_no_call():
    route = respx.post(URL).respond(json=[])
    outcome = await make_reranker().rerank("q", [])
    assert outcome.status == "reranked"
    assert outcome.order == []
    assert outcome.scores == []
    assert not route.called


@respx.mock
async def test_texts_truncated_to_512_chars():
    route = respx.post(URL).respond(json=[{"index": 0, "score": 0.5}])
    await make_reranker().rerank("q", ["x" * 2000])
    body = json.loads(route.calls.last.request.content)
    assert body["query"] == "q"
    assert body["texts"] == ["x" * 512]
