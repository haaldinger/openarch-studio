"""Health endpoint: reports component reachability without requiring auth."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


@respx.mock
def test_health_reports_component_states(client: TestClient) -> None:
    respx.get("http://openarch.test/actuator/health").mock(return_value=httpx.Response(200))
    respx.get("http://tika.test/version").mock(return_value=httpx.Response(200))
    respx.get("http://model.test/v1/models").mock(return_value=httpx.Response(200))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "openarch": "up", "tika": "up", "model": "up"}


@respx.mock
def test_health_marks_unreachable_components_down(client: TestClient) -> None:
    respx.get("http://openarch.test/actuator/health").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://tika.test/version").mock(return_value=httpx.Response(200))
    respx.get("http://model.test/v1/models").mock(return_value=httpx.Response(503))

    body = client.get("/api/health").json()

    assert body["openarch"] == "down"
    assert body["tika"] == "up"
    assert body["model"] == "degraded"
