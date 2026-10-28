"""Readable access endpoint, principal search, and the usernames-param fix."""

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
PERSONA_IDS = [
    "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f11",
    "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f12",
    "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f13",
    "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f14",
    "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f15",
]
U1 = {"id": "u1", "username": "una", "firstName": "Una", "lastName": "X", "email": "u@x.test"}
SALES = {"id": "g-sales", "name": "sales"}


def _sign_in(client: TestClient, username: str = "admin") -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    response = client.post("/api/session", json={"username": username, "password": "p"})
    assert response.status_code == 200


def _demo_client(settings: Settings) -> TestClient:
    demo = settings.model_copy(update={"demo_mode": True, "demo_users_file": REAL_FILE})
    return TestClient(create_app(demo))


def _doc(doc_id: str, parent: str, title: str, acl: list | None = None) -> httpx.Response:
    body: dict = {"sys_id": doc_id, "sys_title": title, "sys_parentId": parent}
    if acl is not None:
        body["sys_acl"] = acl
    return httpx.Response(200, json=body)


def _mock_doc(doc_id: str, response: httpx.Response) -> None:
    respx.get(f"{OA}/api/documents/{doc_id}").mock(return_value=response)


def _mock_effective(doc_id: str, perms: list | None = None) -> respx.Route:
    return respx.get(f"{OA}/api/documents/{doc_id}/fulleffectivepermissions").mock(
        return_value=httpx.Response(
            200, json={"sys_id": doc_id, "fullEffectivePermissions": perms or []}
        )
    )


@respx.mock
def test_access_splits_local_and_inherited(client: TestClient) -> None:
    _sign_in(client)
    _mock_doc(
        "d1",
        _doc(
            "d1",
            "P1",
            "Doc",
            [{"permission": "ReadWrite", "granted": True, "status": "EFFECTIVE", "user": U1}],
        ),
    )
    _mock_doc(
        "P1",
        _doc(
            "P1",
            ROOT_ID,
            "Sales",
            [
                {
                    "permission": "Read",
                    "granted": True,
                    "status": "PENDING",
                    "begin": "2026-10-28T10:00:00Z",
                    "end": "2026-10-28T16:06:07Z",
                    "group": SALES,
                }
            ],
        ),
    )

    response = client.get("/api/documents/d1/access")

    assert response.status_code == 200
    rules = response.json()["rules"]
    assert response.json()["canManage"] is True
    assert rules[0] == {
        "principal": {"kind": "user", "id": "u1", "name": "una"},
        "permission": "ReadWrite",
        "granted": True,
        "begin": None,
        "end": None,
        "status": "EFFECTIVE",
        "source": {"kind": "local", "id": "d1", "title": "Doc"},
    }
    assert rules[1]["principal"] == {"kind": "group", "id": "g-sales", "name": "sales"}
    assert rules[1]["source"] == {"kind": "inherited", "id": "P1", "title": "Sales"}
    assert rules[1]["status"] == "PENDING"
    assert rules[1]["begin"] == "2026-10-28T10:00:00Z"
    assert rules[1]["end"] == "2026-10-28T16:06:07Z"
    assert len(rules) == 2


@respx.mock
def test_access_skips_unreadable_ancestor(client: TestClient) -> None:
    _sign_in(client)
    _mock_doc(
        "d1",
        _doc("d1", "P1", "Doc", [{"permission": "Read", "granted": True, "status": "EFFECTIVE", "user": U1}]),
    )
    _mock_doc("P1", httpx.Response(403))

    response = client.get("/api/documents/d1/access")

    assert response.status_code == 200
    assert [r["source"]["kind"] for r in response.json()["rules"]] == ["local"]


@respx.mock
def test_access_without_manage_security(client: TestClient) -> None:
    _sign_in(client)
    _mock_doc("d1", _doc("d1", ROOT_ID, "Doc"))

    body = client.get("/api/documents/d1/access").json()

    assert body["canManage"] is False
    assert body["rules"] == []


@respx.mock
def test_access_document_not_found(client: TestClient) -> None:
    _sign_in(client)
    _mock_doc("d1", httpx.Response(404))

    assert client.get("/api/documents/d1/access").status_code == 404


@respx.mock
def test_effective_uses_usernames_param_with_ids_in_demo(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client)
    _mock_doc("d1", _doc("d1", ROOT_ID, "Doc", []))
    route = _mock_effective(
        "d1",
        [
            {"userId": PERSONA_IDS[2], "userPermissions": ["Read"]},
            {"userId": PERSONA_IDS[4], "userPermissions": []},
        ],
    )

    effective = client.get("/api/documents/d1/access").json()["effective"]

    assert route.calls.last.request.url.params["usernames"] == ",".join(PERSONA_IDS)
    assert effective[0] == {
        "userId": PERSONA_IDS[2],
        "username": "sam",
        "label": "Sales rep",
        "permissions": ["Read"],
    }
    assert effective[1]["username"] == "cory"
    assert "password" not in str(effective).lower()


@respx.mock
def test_manager_outside_demo_gets_own_permissions_from_document(client: TestClient) -> None:
    _sign_in(client)
    body = {
        "sys_id": "d1",
        "sys_parentId": ROOT_ID,
        "sys_acl": [],
        "sys_effectivePermissions": ["Read", "ManageSecurity"],
    }
    _mock_doc("d1", httpx.Response(200, json=body))
    route = _mock_effective("d1")

    response = client.get("/api/documents/d1/access")

    assert response.status_code == 200
    assert response.json()["canManage"] is True
    assert response.json()["effective"] == [
        {"userId": None, "username": "admin", "permissions": ["Read", "ManageSecurity"]}
    ]
    assert not route.called


@respx.mock
def test_non_manager_gets_own_permissions_without_effective_call(settings: Settings) -> None:
    client = _demo_client(settings)
    _sign_in(client, "sam")
    body = {"sys_id": "d1", "sys_parentId": ROOT_ID, "sys_effectivePermissions": ["Read"]}
    _mock_doc("d1", httpx.Response(200, json=body))
    route = respx.get(f"{OA}/api/documents/d1/fulleffectivepermissions").mock(
        return_value=httpx.Response(401)
    )

    response = client.get("/api/documents/d1/access")

    assert response.status_code == 200
    assert response.json() == {
        "canManage": False,
        "rules": [],
        "effective": [
            {"userId": None, "username": "sam", "label": "Sales rep", "permissions": ["Read"]}
        ],
    }
    assert not route.called
@respx.mock
def test_principals_merges_users_and_groups(settings: Settings) -> None:


    client = _demo_client(settings)
    _sign_in(client)
    respx.get(f"{OA}/api/user", params={"name": "sa"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": PERSONA_IDS[2], "username": "sam", "firstName": "S", "lastName": "M", "email": "s@x"}],
        )
    )
    respx.get(f"{OA}/api/group", params={"name": "sa"}).mock(
        return_value=httpx.Response(200, json=[SALES])
    )

    response = client.get("/api/principals", params={"q": "sa"})

    assert response.status_code == 200
    assert response.json() == [
        {"kind": "user", "id": PERSONA_IDS[2], "name": "sam", "label": "Sales rep"},
        {"kind": "group", "id": "g-sales", "name": "sales"},
    ]
    assert client.get("/api/principals", params={"q": ""}).status_code == 400


@respx.mock
def test_principals_capped_at_20(client: TestClient) -> None:
    _sign_in(client)
    respx.get(f"{OA}/api/user").mock(
        return_value=httpx.Response(200, json=[{"id": f"u{i}", "username": f"u{i}"} for i in range(30)])
    )
    respx.get(f"{OA}/api/group").mock(return_value=httpx.Response(200, json=[SALES]))

    assert len(client.get("/api/principals", params={"q": "u"}).json()) == 20


@respx.mock
def test_existing_acl_route_sends_usernames(client: TestClient) -> None:
    _sign_in(client)
    route = respx.get(f"{OA}/api/documents/doc1/fulleffectiveacl").mock(
        return_value=httpx.Response(200, json={"fullEffectiveACL": []})
    )

    assert client.get("/api/documents/doc1/acl", params={"usernames": "a1,b2"}).status_code == 200

    params = route.calls.last.request.url.params
    assert params["usernames"] == "a1,b2"
    assert "users" not in params
