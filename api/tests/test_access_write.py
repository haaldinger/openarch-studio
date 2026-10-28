"""Write access: PUT /access, and access on upload and folder create."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

OA = "http://openarch.test"
ROOT_ID = "00000000-0000-0000-0000-000000000000"
ROOT = f"{OA}/api/documents/{ROOT_ID}"
SALES_RULE = {"principal": {"kind": "group", "id": "g-sales"}, "permission": "Read"}
SALES_ACE = {"granted": True, "permission": "Read", "group": {"id": "g-sales"}}
PDF = {"file": ("a.pdf", b"%PDF-1.4 data", "application/pdf")}


def _sign_in(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    assert client.post("/api/session", json={"username": "admin", "password": "p"}).status_code == 200


def _mock_get_after_update() -> None:
    respx.get(f"{OA}/api/documents/d1").mock(
        return_value=httpx.Response(
            200,
            json={
                "sys_id": "d1",
                "sys_title": "Doc",
                "sys_parentId": ROOT_ID,
                "sys_acl": [{**SALES_ACE, "status": "EFFECTIVE", "group": {"id": "g-sales", "name": "sales"}}],
            },
        )
    )


@respx.mock
def test_put_access_sends_local_rules_as_sys_acl(client: TestClient) -> None:
    _sign_in(client)
    put = respx.put(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(200, json={}))
    _mock_get_after_update()

    response = client.put("/api/documents/d1/access", json={"rules": [SALES_RULE]})

    assert response.status_code == 200
    assert json.loads(put.calls.last.request.read()) == {"sys_acl": [SALES_ACE]}
    body = response.json()
    assert body["canManage"] is True
    assert body["rules"][0]["principal"] == {"kind": "group", "id": "g-sales", "name": "sales"}
    assert body["rules"][0]["source"]["kind"] == "local"


@respx.mock
def test_put_access_forbidden_message(client: TestClient) -> None:
    _sign_in(client)
    respx.put(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(403))

    response = client.put("/api/documents/d1/access", json={"rules": [SALES_RULE]})

    assert response.status_code == 403
    assert response.json()["detail"] == "You don't have permission to change access here"


@respx.mock
def test_put_access_conflict_message(client: TestClient) -> None:
    _sign_in(client)
    respx.put(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(409))

    response = client.put("/api/documents/d1/access", json={"rules": [SALES_RULE]})

    assert response.status_code == 409
    assert response.json()["detail"] == "Access changed meanwhile; reloaded"


@respx.mock
def test_put_access_rejects_bogus_permission_before_openarch(client: TestClient) -> None:
    _sign_in(client)
    put = respx.put(f"{OA}/api/documents/d1")

    bad = {"principal": {"kind": "group", "id": "g"}, "permission": "Bogus"}
    response = client.put("/api/documents/d1/access", json={"rules": [bad]})

    assert response.status_code == 400
    assert not put.called


@respx.mock
def test_upload_with_access_includes_sys_acl(client: TestClient) -> None:
    _sign_in(client)
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl1"}))
    create = respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))
    respx.get(f"{OA}/api/documents/doc1").mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))

    response = client.post("/api/documents", files=PDF, data={"access": json.dumps([SALES_RULE])})

    assert response.status_code == 201
    assert json.loads(create.calls.last.request.read()) == {
        "sys_primaryType": "SysFile",
        "sys_title": "a.pdf",
        "sys_name": "a.pdf",
        "sysfile_blob": {"uploadId": "upl1"},
        "sys_acl": [SALES_ACE],
    }


@respx.mock
def test_upload_without_access_has_no_sys_acl(client: TestClient) -> None:
    _sign_in(client)
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl1"}))
    create = respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))
    respx.get(f"{OA}/api/documents/doc1").mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))

    response = client.post("/api/documents", files=PDF)

    assert response.status_code == 201
    assert "sys_acl" not in json.loads(create.calls.last.request.read())


@respx.mock
def test_upload_invalid_access_fails_before_any_openarch_call(client: TestClient) -> None:
    _sign_in(client)
    upload = respx.post(f"{OA}/api/upload")
    bad = [{"principal": {"kind": "group", "id": "g"}, "permission": "Bogus"}]

    response = client.post("/api/documents", files=PDF, data={"access": json.dumps(bad)})

    assert response.status_code == 400
    assert not upload.called


@respx.mock
def test_upload_access_forbidden_message(client: TestClient) -> None:
    _sign_in(client)
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl1"}))
    respx.post(ROOT).mock(return_value=httpx.Response(403))

    response = client.post("/api/documents", files=PDF, data={"access": json.dumps([SALES_RULE])})

    assert response.status_code == 403
    assert response.json()["detail"] == "You can't set access in this folder"


@respx.mock
def test_upload_forbidden_without_access_keeps_existing_message(client: TestClient) -> None:
    _sign_in(client)
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl1"}))
    respx.post(ROOT).mock(return_value=httpx.Response(403))

    response = client.post("/api/documents", files=PDF)

    assert response.status_code == 403
    assert response.json()["detail"] == "Not permitted"


@respx.mock
def test_create_folder_with_access(client: TestClient) -> None:
    _sign_in(client)
    create = respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "f1"}))

    response = client.post("/api/folders", json={"title": "HR", "access": [SALES_RULE]})

    assert response.status_code == 201
    assert json.loads(create.calls.last.request.read()) == {
        "sys_primaryType": "SysFolder",
        "sys_title": "HR",
        "sys_name": "HR",
        "sys_acl": [SALES_ACE],
    }


@respx.mock
def test_create_folder_without_access_has_no_sys_acl(client: TestClient) -> None:
    _sign_in(client)
    create = respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "f1"}))

    response = client.post("/api/folders", json={"title": "HR"})

    assert response.status_code == 201
    assert "sys_acl" not in json.loads(create.calls.last.request.read())


@respx.mock
def test_create_folder_access_forbidden_message(client: TestClient) -> None:
    _sign_in(client)
    respx.post(ROOT).mock(return_value=httpx.Response(403))

    response = client.post("/api/folders", json={"title": "HR", "access": [SALES_RULE]})

    assert response.status_code == 403
    assert response.json()["detail"] == "You can't set access in this folder"
