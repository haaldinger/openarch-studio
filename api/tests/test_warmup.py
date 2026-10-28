"""Startup warm-up of the model runtime."""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

from app.config import Settings
from app.warmup import warm_up

CHAT = "http://model.test/v1/chat/completions"


def make_settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, model_base_url="http://model.test/v1", **kw)


def models_called(route: respx.Route) -> list[str]:
    return sorted(json.loads(call.request.content)["model"] for call in route.calls)


@respx.mock
async def test_warm_up_pings_extract_and_chat_and_swallows_errors() -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        return httpx.Response(500 if model == "ex" else 200, json={})

    route = respx.post(CHAT).mock(side_effect=reply)
    await warm_up(make_settings(extract_model="ex", chat_model="ch"))
    assert models_called(route) == ["ch", "ex"]
    body = json.loads(route.calls[0].request.content)
    assert body["max_tokens"] == 1 and body["stream"] is False


@respx.mock
async def test_warm_up_swallows_connection_errors() -> None:
    respx.post(CHAT).mock(side_effect=httpx.ConnectError("down"))
    await warm_up(make_settings(extract_model="ex", chat_model="ch"))


@respx.mock
async def test_warm_up_pings_a_shared_model_once() -> None:
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json={}))
    await warm_up(make_settings(extract_model="same", chat_model="same"))
    assert models_called(route) == ["same"]


@respx.mock
def test_lifespan_skips_warm_up_in_baseline_mode() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json={}))
    app = create_app(make_settings(extract_model="ex", chat_model="ch", baseline_mode=True))
    with TestClient(app):
        assert app.state.warmup_task is None
    assert not route.called


@respx.mock
def test_lifespan_schedules_warm_up_without_awaiting_it() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    respx.post(CHAT).mock(return_value=httpx.Response(200, json={}))
    app = create_app(make_settings(extract_model="ex", chat_model="ch"))
    with TestClient(app):
        assert app.state.warmup_task is not None
