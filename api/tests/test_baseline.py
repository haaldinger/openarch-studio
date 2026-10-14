"""Baseline mode: one switch that leaves only native OpenArch capabilities."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _baseline_client() -> TestClient:
    settings = Settings(
        openarch_url="http://openarch.test",
        tika_url="http://tika.test",
        model_base_url="http://model.test/v1",
        baseline_mode=True,
    )
    return TestClient(create_app(settings))


def test_config_defaults_to_extensions_on(client: TestClient) -> None:
    assert client.get("/api/config").json() == {"baselineMode": False}


def test_config_reports_baseline_when_on() -> None:
    assert _baseline_client().get("/api/config").json()["baselineMode"] is True


def test_capabilities_mark_extensions_disabled_in_baseline() -> None:
    body = _baseline_client().get("/api/capabilities").json()
    assert body["baselineMode"] is True
    assert body["extensions"] and all(ext["disabled"] for ext in body["extensions"])
    # Native capabilities remain, unmarked.
    assert body["native"]


def test_baseline_gates_extension_routes_but_keeps_native() -> None:
    c = _baseline_client()
    # Every extension surface is refused.
    assert c.get("/api/jobs").status_code == 403
    # Native-facing endpoints stay reachable.
    assert c.get("/api/capabilities").status_code == 200
    assert c.get("/api/config").status_code == 200


def test_extensions_reachable_by_default(client: TestClient) -> None:
    assert client.get("/api/jobs").status_code == 200


def test_put_config_requires_a_session(client: TestClient) -> None:
    # The live switch must not be flippable by an anonymous caller.
    assert client.put("/api/config", json={"baselineMode": True}).status_code == 401


def test_baseline_flips_live_without_restart(client: TestClient) -> None:
    # Same app instance: mutating runtime state gates extensions immediately.
    assert client.get("/api/jobs").status_code == 200
    client.app.state.baseline_mode = True
    assert client.get("/api/config").json() == {"baselineMode": True}
    assert client.get("/api/jobs").status_code == 403
    client.app.state.baseline_mode = False
    assert client.get("/api/jobs").status_code == 200
