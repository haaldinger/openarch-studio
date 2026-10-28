"""Enrichment jobs belong to the identity that started them."""

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
ROOT_ID = "00000000-0000-0000-0000-000000000000"
ROOT = f"{OA}/api/documents/{ROOT_ID}"
QUERY = f"{OA}/api/query"


def _basic(username: str, password: str = "password") -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def _mock_user(username: str) -> None:
    respx.get(ROOT, headers={"Authorization": _basic(username)}).mock(
        return_value=httpx.Response(200, json={"sys_id": "root"})
    )
    respx.post(QUERY, headers={"Authorization": _basic(username)}).mock(
        return_value=httpx.Response(200, json={"documents": []})
    )


def _mock_upload() -> None:
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl1"}))
    respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))
    respx.get(f"{OA}/api/documents/doc1").mock(
        return_value=httpx.Response(200, json={"sys_id": "doc1", "sys_title": "a.pdf"})
    )


def _demo_client(settings: Settings) -> TestClient:
    demo = settings.model_copy(update={"demo_mode": True, "demo_users_file": REAL_FILE})
    return TestClient(create_app(demo))


def _sign_in(client: TestClient, username: str) -> None:
    response = client.post("/api/session", json={"username": username, "password": "password"})
    assert response.status_code == 200


@respx.mock
def test_jobs_listed_only_for_active_identity(settings: Settings) -> None:
    for name in ("admin", "sam"):
        _mock_user(name)
    _mock_upload()
    client = _demo_client(settings)
    _sign_in(client, "admin")
    assert client.post("/api/documents", files={"file": ("a.pdf", b"%PDF data", "application/pdf")}).status_code == 201

    client.post("/api/session/act-as", json={"username": "sam"})
    assert client.get("/api/jobs").json() == {"jobs": []}

    client.post("/api/session/act-as", json={"username": "admin"})
    assert len(client.get("/api/jobs").json()["jobs"]) == 1


@respx.mock
def test_retry_other_identity_job_is_404(settings: Settings) -> None:
    for name in ("admin", "sam"):
        _mock_user(name)
    _mock_upload()
    client = _demo_client(settings)
    _sign_in(client, "admin")
    job_id = client.post(
        "/api/documents", files={"file": ("a.pdf", b"%PDF data", "application/pdf")}
    ).json()["_studioJobId"]

    client.post("/api/session/act-as", json={"username": "sam"})

    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 404
