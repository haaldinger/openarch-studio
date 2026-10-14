"""Session boundary: login, cookie, TTL, logout, and OpenArch auth/outage mapping."""

from __future__ import annotations

import time

import httpx
import respx
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, SessionStore
from app.config import Settings
from app.main import create_app
from app.models import Credentials

ROOT = "http://openarch.test/api/documents/00000000-0000-0000-0000-000000000000"


@respx.mock
def test_login_sets_httponly_session_cookie(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))

    response = client.post("/api/session", json={"username": "admin", "password": "password"})

    assert response.status_code == 200
    assert response.json() == {"username": "admin"}
    cookie = response.headers.get("set-cookie", "")
    assert COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "admin" not in cookie  # opaque id, never the username/credentials


@respx.mock
def test_invalid_credentials_return_401(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(401))

    response = client.post("/api/session", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert COOKIE_NAME not in response.headers.get("set-cookie", "")


@respx.mock
def test_openarch_401_invalidates_session_and_outage_returns_503(client: TestClient) -> None:
    # Outage on login path is a distinct 503, not an auth failure.
    respx.get(ROOT).mock(side_effect=httpx.ConnectError("down"))
    outage = client.post("/api/session", json={"username": "admin", "password": "password"})
    assert outage.status_code == 503

    # A rejected credential invalidates rather than degrades.
    respx.get(ROOT).mock(return_value=httpx.Response(401))
    rejected = client.post("/api/session", json={"username": "admin", "password": "password"})
    assert rejected.status_code == 401


@respx.mock
def test_session_roundtrip_and_logout(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    client.post("/api/session", json={"username": "admin", "password": "password"})

    assert client.get("/api/session").json() == {"username": "admin"}

    client.delete("/api/session")
    assert client.get("/api/session").status_code == 401


def test_unauthenticated_session_read_is_401(client: TestClient) -> None:
    assert client.get("/api/session").status_code == 401


def test_session_store_expires_entries() -> None:
    store = SessionStore(ttl_seconds=0)
    sid = store.create(Credentials(username="a", password="b"))
    time.sleep(0.01)
    assert store.get(sid) is None


def test_settings_do_not_leak_password_in_repr() -> None:
    creds = Credentials(username="admin", password="s3cret")
    assert "s3cret" not in repr(creds)
    assert creds.basic_auth() == ("admin", "s3cret")


def test_session_app_uses_real_store() -> None:
    app = create_app(Settings(openarch_url="http://openarch.test"))
    assert isinstance(app.state.sessions, SessionStore)
