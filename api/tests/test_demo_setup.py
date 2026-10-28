"""Demo setup (POST /api/demo/setup) and reset (DELETE /api/demo)."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.demo import load_demo_users
from app.demo_setup import _find_child
from app.main import create_app
from app.models import Credentials
from app.openarch import OpenArchClient

ROOT_DIR = Path(__file__).resolve().parents[2] / "demo"
USERS_FILE = str(ROOT_DIR / "openarch-users.yml")
SAMPLES = ROOT_DIR / "samples"
OA = "http://openarch.test"
ROOT_ID = "00000000-0000-0000-0000-000000000000"
ADMIN_AUTH = "Basic " + base64.b64encode(b"admin:password").decode()
USERS = load_demo_users(USERS_FILE)
FOLDERS = {"Company": "members", "Finance": "finance", "HR": "hr", "Sales": "sales"}
TITLES = {name: f"Demo · {name}" for name in FOLDERS}


def ace(group: str) -> dict[str, Any]:
    return {"granted": True, "permission": "Read", "group": {"id": USERS.group_ids[group]}}


class FakeOpenArch:
    """Just enough of OpenArch: folders/files by parent, upload, create, delete."""

    def __init__(self) -> None:
        self.children: dict[str, list[dict[str, Any]]] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []  # (parentId, payload)
        self.deleted: list[str] = []
        self.requests: list[httpx.Request] = []
        self._n = 0

    def seed(self, parent: str, title: str, primary_type: str = "SysFolder") -> str:
        self._n += 1
        doc_id = f"id{self._n}"
        self.children.setdefault(parent, []).append(
            {"sys_id": doc_id, "sys_title": title, "sys_primaryType": primary_type}
        )
        return doc_id

    def install(self) -> None:
        respx.get(re.compile(rf"{OA}/api/documents/[^/]+$")).mock(side_effect=self._get)
        respx.post(f"{OA}/api/query").mock(side_effect=self._query)
        respx.post(f"{OA}/api/upload").mock(side_effect=self._upload)
        respx.post(re.compile(rf"{OA}/api/documents/[^/]+$")).mock(side_effect=self._create)
        respx.delete(re.compile(rf"{OA}/api/documents/[^/]+$")).mock(side_effect=self._delete)

    def _get(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"sys_id": request.url.path.rsplit("/", 1)[1]})

    def _query(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = json.loads(request.content)
        query = payload["query"]
        parent = re.search(r"sys_parentId = '([^']+)'", query).group(1)  # type: ignore[union-attr]
        docs = sorted(self.children.get(parent, []), key=lambda d: d["sys_title"])
        title = re.search(r"sys_title = '((?:[^']|'')*)'", query)
        if title:
            wanted = title.group(1).replace("''", "'")
            docs = [d for d in docs if d["sys_title"] == wanted]
        return httpx.Response(200, json={"documents": docs[: payload.get("limit", 100)]})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(201, json={"id": f"upl-{request.url.params['fileName']}"})

    def _create(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parent = request.url.path.rsplit("/", 1)[1]
        payload = json.loads(request.content)
        self.created.append((parent, payload))
        doc_id = self.seed(parent, payload["sys_title"], payload["sys_primaryType"])
        return httpx.Response(200, json={"sys_id": doc_id})

    def _delete(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.deleted.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(204)

    def id_of(self, parent: str, title: str) -> str:
        return next(d["sys_id"] for d in self.children[parent] if d["sys_title"] == title)


@pytest.fixture
def demo_client(settings: Settings) -> TestClient:
    demo = settings.model_copy(
        update={"demo_mode": True, "demo_users_file": USERS_FILE, "demo_samples_dir": str(SAMPLES)}
    )
    client = TestClient(create_app(demo))
    client.runs = []  # type: ignore[attr-defined]

    async def fake_run(job: Any, credentials: Any, **kwargs: Any) -> None:
        client.runs.append((job, credentials, kwargs))  # type: ignore[attr-defined]

    client.app.state.enrichment.run = fake_run  # type: ignore[attr-defined]
    return client


def _sign_in(client: TestClient, username: str = "admin") -> None:
    response = client.post("/api/session", json={"username": username, "password": "password"})
    assert response.status_code == 200


def _folder_payloads(fake: FakeOpenArch) -> dict[str, dict[str, Any]]:
    return {p["sys_title"]: p for _, p in fake.created if p["sys_primaryType"] == "SysFolder"}


def _file_payloads(fake: FakeOpenArch) -> dict[str, dict[str, Any]]:
    return {p["sys_title"]: p for _, p in fake.created if p["sys_primaryType"] == "SysFile"}


@respx.mock
def test_setup_creates_folders_with_group_acls(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 200
    body = response.json()
    folders = _folder_payloads(fake)
    assert set(folders) == set(TITLES.values())
    for name, group in FOLDERS.items():
        assert folders[TITLES[name]]["sys_acl"] == [ace(group)]
    assert body["folders"] == {name: fake.id_of(ROOT_ID, TITLES[name]) for name in FOLDERS}
    assert len(body["jobs"]) == 8
    uploaded = _file_payloads(fake)
    assert set(uploaded) == {p.name for p in SAMPLES.glob("*/*.md")}
    assert all(payload["sysfile_blob"]["uploadId"].startswith("upl-") for payload in uploaded.values())


@respx.mock
def test_department_folders_have_no_shared_parent(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)

    demo_client.post("/api/demo/setup")

    folders = [(parent, p) for parent, p in fake.created if p["sys_primaryType"] == "SysFolder"]
    assert len(folders) == 4
    assert all(parent == ROOT_ID for parent, _ in folders)
    members = USERS.group_ids["members"]
    granting = {p["sys_title"] for _, p in folders if any(a["group"]["id"] == members for a in p["sys_acl"])}
    assert granting == {"Demo · Company"}


@respx.mock
def test_setup_is_idempotent(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)
    first = demo_client.post("/api/demo/setup").json()
    created = len(fake.created)
    runs = len(demo_client.runs)  # type: ignore[attr-defined]

    second = demo_client.post("/api/demo/setup")

    assert second.status_code == 200
    assert len(fake.created) == created
    assert len(demo_client.runs) == runs  # type: ignore[attr-defined]
    assert second.json()["folders"] == first["folders"]
    assert second.json()["jobs"] == []


@respx.mock
def test_setup_only_uploads_missing_files(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    hr = fake.seed(ROOT_ID, "Demo · HR")
    fake.seed(hr, "salary-bands.md", "SysFile")
    fake.install()
    _sign_in(demo_client)

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 200
    assert "salary-bands.md" not in _file_payloads(fake)
    assert "bonus-policy-2027.md" in _file_payloads(fake)
    assert "Demo · HR" not in _folder_payloads(fake)
    assert response.json()["folders"]["HR"] == hr


@respx.mock
def test_setup_finds_folder_beyond_the_first_page_of_root_children(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    for i in range(150):
        fake.seed(ROOT_ID, f"A item {i:03d}")
    hr = fake.seed(ROOT_ID, "Demo · HR")
    fake.install()
    _sign_in(demo_client)

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 200
    assert "Demo · HR" not in _folder_payloads(fake)
    assert response.json()["folders"]["HR"] == hr


@respx.mock
def test_reset_finds_folder_beyond_the_first_page_of_root_children(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    for i in range(150):
        fake.seed(ROOT_ID, f"A item {i:03d}")
    hr = fake.seed(ROOT_ID, "Demo · HR")
    fake.install()
    _sign_in(demo_client)

    assert demo_client.delete("/api/demo").status_code == 204
    assert fake.deleted == [hr]


@respx.mock
async def test_title_with_quote_is_escaped_in_lookup() -> None:
    fake = FakeOpenArch()
    folder = fake.seed(ROOT_ID, "Demo · HR")
    fake.seed(folder, "o'brien.md", "SysFile")
    fake.install()

    client = OpenArchClient(OA, Credentials(username="admin", password=SecretStr("password")))
    found = await _find_child(client, folder, "o'brien.md")

    assert found is not None
    assert "o''brien.md" in json.loads(fake.requests[-1].content)["query"]


@respx.mock
def test_setup_uses_origin_credentials_while_acting_as(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)
    assert demo_client.post("/api/session/act-as", json={"username": "sam"}).status_code == 200
    fake.requests.clear()

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 200
    assert fake.requests
    assert {r.headers["Authorization"] for r in fake.requests} == {ADMIN_AUTH}
    runs = demo_client.runs  # type: ignore[attr-defined]
    assert runs and all(c.username == "admin" for _, c, _ in runs)
    assert all(job.owner == "admin" for job, _, _ in runs)


@respx.mock
def test_q4_pricing_gets_cory_read(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)

    demo_client.post("/api/demo/setup")

    uploaded = _file_payloads(fake)
    cory = {"granted": True, "permission": "Read", "user": {"id": USERS.personas["cory"].user_id}}
    assert uploaded["q4-pricing.md"]["sys_acl"] == [cory]
    assert all("sys_acl" not in p for name, p in uploaded.items() if name != "q4-pricing.md")


@respx.mock
def test_setup_forbidden_for_non_admin(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client, "sam")

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 403
    assert not fake.created


@respx.mock
def test_setup_forbidden_when_demo_off(client: TestClient) -> None:
    FakeOpenArch().install()
    _sign_in(client)

    assert client.post("/api/demo/setup").status_code == 403


@respx.mock
def test_setup_missing_samples_dir_is_a_clear_error(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    demo_client.app.state.settings.demo_samples_dir = ""  # type: ignore[attr-defined]
    _sign_in(demo_client)

    response = demo_client.post("/api/demo/setup")

    assert response.status_code == 500
    assert "STUDIO_DEMO_SAMPLES_DIR" in response.json()["detail"]
    assert not fake.created


@respx.mock
def test_reset_deletes_demo_folders(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    demo = [fake.seed(ROOT_ID, title) for title in TITLES.values()]
    fake.seed(ROOT_ID, "Other")
    fake.install()
    _sign_in(demo_client)

    response = demo_client.delete("/api/demo")

    assert response.status_code == 204
    assert sorted(fake.deleted) == sorted(demo)


@respx.mock
def test_reset_without_demo_folder_is_a_noop(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.install()
    _sign_in(demo_client)

    assert demo_client.delete("/api/demo").status_code == 204
    assert fake.deleted == []


@respx.mock
def test_reset_forbidden_for_non_admin(demo_client: TestClient) -> None:
    fake = FakeOpenArch()
    fake.seed(ROOT_ID, "Demo · HR")
    fake.install()
    _sign_in(demo_client, "sam")

    assert demo_client.delete("/api/demo").status_code == 403
    assert fake.deleted == []
