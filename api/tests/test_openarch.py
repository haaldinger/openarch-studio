"""Typed OpenArch client: auth probe, status mapping, and transport errors."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.models import Credentials
from app.openarch import (
    OpenArchAuthError,
    OpenArchClient,
    OpenArchForbidden,
    OpenArchNotFound,
    OpenArchUnavailable,
)

ROOT = "http://openarch.test/api/documents/00000000-0000-0000-0000-000000000000"


def make_client() -> OpenArchClient:
    return OpenArchClient("http://openarch.test", Credentials(username="admin", password="password"))


@respx.mock
async def test_authenticate_returns_username_on_200() -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    assert await make_client().authenticate() == "admin"


@respx.mock
async def test_authenticate_sends_basic_auth_and_repository_header() -> None:
    route = respx.get(ROOT).mock(return_value=httpx.Response(200, json={}))
    await make_client().authenticate()
    request = route.calls.last.request
    assert request.headers["authorization"].startswith("Basic ")
    assert request.headers["HXCS-Repository"] == "default"


@respx.mock
async def test_status_codes_map_to_typed_errors() -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(401))
    with pytest.raises(OpenArchAuthError):
        await make_client().authenticate()

    respx.get(ROOT).mock(return_value=httpx.Response(403))
    with pytest.raises(OpenArchForbidden):
        await make_client().authenticate()

    respx.get(ROOT).mock(return_value=httpx.Response(404))
    with pytest.raises(OpenArchNotFound):
        await make_client().authenticate()

    respx.get(ROOT).mock(return_value=httpx.Response(503))
    with pytest.raises(OpenArchUnavailable):
        await make_client().authenticate()


@respx.mock
async def test_transport_failure_maps_to_unavailable() -> None:
    respx.get(ROOT).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(OpenArchUnavailable):
        await make_client().authenticate()


@respx.mock
async def test_query_posts_payload_and_returns_json() -> None:
    route = respx.post("http://openarch.test/api/query").mock(
        return_value=httpx.Response(200, json={"documents": [], "totalCount": 0})
    )
    result = await make_client().query({"query": "SELECT * FROM SysContent", "limit": 5})
    assert result["totalCount"] == 0
    assert route.calls.last.request.headers["HXCS-Repository"] == "default"


@respx.mock
async def test_ensure_mixin_adds_once_and_skips_when_present() -> None:
    doc = "http://openarch.test/api/documents/d1"
    get = respx.get(doc).mock(return_value=httpx.Response(200, json={"sys_mixinTypes": ["SysHasEmbeddings"]}))
    put = respx.put(doc).mock(return_value=httpx.Response(200, json={}))
    await make_client().ensure_mixin("d1", "CinContext")
    assert json.loads(put.calls.last.request.content) == {
        "sys_mixinTypes": ["SysHasEmbeddings", "CinContext"]
    }

    get.mock(return_value=httpx.Response(200, json={"sys_mixinTypes": ["CinContext"]}))
    put.reset()
    await make_client().ensure_mixin("d1", "CinContext")
    assert put.call_count == 0
