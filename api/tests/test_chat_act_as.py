"""Chat/search run as a demo persona and report a scoped folder turning unreadable."""

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
EMBED = "http://model.test/v1/embeddings"
CHAT = "http://model.test/v1/chat/completions"
VECTOR_QUERY = f"{OA}/api/query/embeddings"
ROOT = f"{OA}/api/documents/00000000-0000-0000-0000-000000000000"
NO_ACCESS = "You no longer have access to this folder"


def _basic(username: str, password: str = "password") -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def _demo_client(settings: Settings) -> TestClient:
    demo = settings.model_copy(update={"demo_mode": True, "demo_users_file": REAL_FILE})
    return TestClient(create_app(demo))


def _sign_in(client: TestClient, username: str) -> None:
    respx.get(ROOT, headers={"Authorization": _basic(username)}).mock(
        return_value=httpx.Response(200, json={"sys_id": "root"})
    )
    response = client.post("/api/session", json={"username": username, "password": "password"})
    assert response.status_code == 200


def _mock_chat_backend() -> respx.Route:
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.get(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(200, json={"sys_id": "d1"}))
    respx.post(CHAT).mock(
        return_value=httpx.Response(200, text='data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]\n\n')
    )
    return respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [{"sysembed_docId": "d1", "sysembed_id": "c1", "sysembed_text": "ctx"}]},
        )
    )


@respx.mock
def test_chat_act_as_uses_persona_credentials(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client, "admin")
    route = _mock_chat_backend()

    response = client.post("/api/chat", json={"question": "what?", "actAs": "erin"})

    assert response.status_code == 200
    assert "event: RUN_FINISHED" in response.text
    assert route.calls.last.request.headers["Authorization"] == _basic("erin")


@respx.mock
def test_chat_act_as_origin_allowed(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client, "admin")
    route = _mock_chat_backend()

    response = client.post("/api/chat", json={"question": "what?", "actAs": "admin"})

    assert response.status_code == 200
    assert route.calls.last.request.headers["Authorization"] == _basic("admin")


@respx.mock
def test_chat_act_as_forbidden_outside_demo(client: TestClient) -> None:
    _sign_in(client, "admin")
    _mock_chat_backend()

    response = client.post("/api/chat", json={"question": "what?", "actAs": "erin"})

    assert response.status_code == 403


@respx.mock
def test_chat_act_as_unknown_persona_forbidden(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client, "admin")
    _mock_chat_backend()

    assert client.post("/api/chat", json={"question": "q", "actAs": "nobody"}).status_code == 403


@respx.mock
def test_chat_scoped_folder_forbidden_message(client: TestClient) -> None:
    _sign_in(client, "admin")
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(VECTOR_QUERY).mock(return_value=httpx.Response(403))

    response = client.post("/api/chat", json={"question": "what?", "scope": "folder-1"})

    assert response.status_code == 200
    assert "event: RUN_ERROR" in response.text
    assert NO_ACCESS in response.text


@respx.mock
def test_search_scoped_folder_forbidden_message(client: TestClient) -> None:
    _sign_in(client, "admin")
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(VECTOR_QUERY).mock(return_value=httpx.Response(403))

    scoped = client.post("/api/search", json={"mode": "semantic", "query": "q", "scope": "folder-1"})
    unscoped = client.post("/api/search", json={"mode": "semantic", "query": "q"})

    assert scoped.status_code == 403
    assert scoped.json()["detail"] == NO_ACCESS
    assert unscoped.status_code == 403
    assert unscoped.json()["detail"] == "Not permitted"


@respx.mock
def test_chat_act_as_forbidden_for_non_admin(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client, "cory")
    route = _mock_chat_backend()

    response = client.post("/api/chat", json={"question": "q", "actAs": "erin"})

    assert response.status_code == 403
    assert not any(call.request.url == VECTOR_QUERY for call in route.calls)
