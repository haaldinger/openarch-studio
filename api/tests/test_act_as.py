"""Session origin/active identities and the demo act-as switch."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

REAL_FILE = str(Path(__file__).resolve().parents[2] / "demo" / "openarch-users.yml")
OA = "http://openarch.test"
ROOT = f"{OA}/api/documents/00000000-0000-0000-0000-000000000000"
QUERY = f"{OA}/api/query"


def _basic(username: str, password: str = "password") -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def _mock_user(username: str, status: int = 200) -> None:
    respx.get(ROOT, headers={"Authorization": _basic(username)}).mock(
        return_value=httpx.Response(status, json={"sys_id": "root"})
    )
    respx.post(QUERY, headers={"Authorization": _basic(username)}).mock(
        return_value=httpx.Response(200, json={"documents": []})
    )


def _demo_client(settings: Settings) -> TestClient:
    demo = settings.model_copy(update={"demo_mode": True, "demo_users_file": REAL_FILE})
    return TestClient(create_app(demo))


def _sign_in(client: TestClient, username: str) -> None:
    response = client.post("/api/session", json={"username": username, "password": "password"})
    assert response.status_code == 200


def _last_query_auth() -> str:
    calls = [c for c in respx.calls if c.request.url.path == "/api/query"]
    return calls[-1].request.headers["Authorization"]


@respx.mock
def test_act_as_persona_runs_requests_as_persona(settings: Settings) -> None:
    for name in ("admin", "sam"):
        _mock_user(name)
    client = _demo_client(settings)
    _sign_in(client, "admin")

    response = client.post("/api/session/act-as", json={"username": "sam"})

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["actingAs"] == {"username": "sam", "label": "Sales rep", "groups": ["sales", "members"]}
    assert body["demoAdmin"] is True
    assert client.get("/api/documents").status_code == 200
    assert _last_query_auth() == _basic("sam")


@respx.mock
def test_back_to_origin(settings: Settings) -> None:
    for name in ("admin", "sam"):
        _mock_user(name)
    client = _demo_client(settings)
    _sign_in(client, "admin")
    client.post("/api/session/act-as", json={"username": "sam"})

    response = client.post("/api/session/act-as", json={"username": "admin"})

    assert response.status_code == 200
    assert response.json()["actingAs"] is None
    client.get("/api/documents")
    assert _last_query_auth() == _basic("admin")
    assert client.get("/api/session").json()["actingAs"] is None


@respx.mock
def test_act_as_rejected_when_demo_off(client: TestClient) -> None:
    _mock_user("admin")
    _sign_in(client, "admin")

    assert client.post("/api/session/act-as", json={"username": "sam"}).status_code == 403


@respx.mock
def test_act_as_rejected_for_non_admin_origin(settings: Settings) -> None:
    _mock_user("sam")
    client = _demo_client(settings)
    _sign_in(client, "sam")

    assert client.post("/api/session/act-as", json={"username": "fiona"}).status_code == 403


@respx.mock
def test_act_as_unknown_persona(settings: Settings) -> None:
    _mock_user("admin")
    client = _demo_client(settings)
    _sign_in(client, "admin")

    assert client.post("/api/session/act-as", json={"username": "nobody"}).status_code == 403


@respx.mock
def test_act_as_persona_without_root_read_succeeds(settings: Settings) -> None:
    _mock_user("admin")
    respx.get(ROOT, headers={"Authorization": _basic("sam")}).mock(
        return_value=httpx.Response(403)
    )
    client = _demo_client(settings)
    _sign_in(client, "admin")

    response = client.post("/api/session/act-as", json={"username": "sam"})

    assert response.status_code == 200
    assert response.json()["actingAs"]["username"] == "sam"


@respx.mock
def test_act_as_persona_signin_failure(settings: Settings) -> None:
    _mock_user("admin")
    _mock_user("sam", status=401)
    client = _demo_client(settings)
    _sign_in(client, "admin")

    response = client.post("/api/session/act-as", json={"username": "sam"})

    assert response.status_code == 502
    assert "Couldn't sign in as sam" in response.json()["detail"]
    assert client.get("/api/session").json()["actingAs"] is None


@respx.mock
def test_session_reports_demo_admin(settings: Settings, client: TestClient) -> None:
    _mock_user("admin")
    _mock_user("sam")
    demo_client = _demo_client(settings)
    _sign_in(demo_client, "admin")
    assert demo_client.get("/api/session").json()["demoAdmin"] is True

    other = _demo_client(settings)
    _sign_in(other, "sam")
    assert other.get("/api/session").json()["demoAdmin"] is False

    _sign_in(client, "admin")
    assert client.get("/api/session").json()["demoAdmin"] is False


@respx.mock
def test_personas_endpoint_hides_passwords(settings: Settings, client: TestClient) -> None:
    _mock_user("admin")
    demo_client = _demo_client(settings)
    _sign_in(demo_client, "admin")

    response = demo_client.get("/api/demo/personas")

    assert response.status_code == 200
    personas = response.json()
    assert {p["username"] for p in personas} == {"fiona", "henry", "sam", "erin", "cory"}
    assert all(p["available"] is True for p in personas)
    assert "password" not in response.text.lower()

    _sign_in(client, "admin")
    assert client.get("/api/demo/personas").status_code == 404


@respx.mock
def test_sign_out_clears_persona(settings: Settings) -> None:
    for name in ("admin", "sam"):
        _mock_user(name)
    client = _demo_client(settings)
    _sign_in(client, "admin")
    client.post("/api/session/act-as", json={"username": "sam"})

    client.delete("/api/session")
    assert client.get("/api/session").status_code == 401

    _sign_in(client, "admin")
    assert client.get("/api/session").json()["actingAs"] is None
