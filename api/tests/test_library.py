"""Library: browse, upload (create+attach), inspect, ACL, and content."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

ROOT_ID = "00000000-0000-0000-0000-000000000000"
ROOT = f"http://openarch.test/api/documents/{ROOT_ID}"
QUERY = "http://openarch.test/api/query"


def _authenticate(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    assert client.post("/api/session", json={"username": "admin", "password": "p"}).status_code == 200


@respx.mock
def test_browse_lists_children_as_summaries(client: TestClient) -> None:
    _authenticate(client)
    respx.post(QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "sys_id": "d1",
                        "sys_title": "Policy.pdf",
                        "sys_name": "Policy.pdf",
                        "sys_primaryType": "SysFile",
                        "sys_isFolderish": False,
                        "sys_parentId": ROOT_ID,
                    }
                ],
                "totalCount": 1,
            },
        )
    )

    response = client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["parentId"] == ROOT_ID
    assert body["documents"][0] == {
        "id": "d1",
        "title": "Policy.pdf",
        "name": "Policy.pdf",
        "primaryType": "SysFile",
        "isFolderish": False,
        "modified": None,
        "mixinTypes": [],
        "documentType": None,
        "parentId": ROOT_ID,
        "access": {"mine": None, "sharedWith": None, "expiresAt": None},
    }


def test_summarize_exposes_document_type() -> None:
    from app.library import summarize

    doc = {"sys_id": "d1", "cinctx_contextProperties": {"document_type": "invoice"}}

    assert summarize(doc)["documentType"] == "invoice"
    assert summarize({"sys_id": "d2"})["documentType"] is None


@pytest.mark.parametrize(
    "props",
    ["oops", ["document_type"], {"document_type": {"a": 1}}, {"document_type": 5}, {"document_type": ""}],
)
def test_summarize_ignores_malformed_extracted_fields(props: object) -> None:
    from app.library import summarize

    doc = {"sys_id": "d1", "cinctx_contextProperties": props}

    assert summarize(doc)["documentType"] is None


@pytest.mark.parametrize(
    ("perms", "mine"),
    [
        (["Read", "ReadWrite", "Write", "ManageSecurity"], "manage"),
        (["Everything"], "manage"),
        (["Read", "Write"], "edit"),
        (["Read", "ReadWrite"], "edit"),
        (["Read"], "read"),
        ([], None),
        (None, None),
    ],
)
def test_summarize_reports_own_access(perms: object, mine: str | None) -> None:
    from app.library import summarize

    assert summarize({"sys_id": "d1", "sys_effectivePermissions": perms})["access"]["mine"] == mine


def test_summarize_shared_with_active_rules_only() -> None:
    from app.library import summarize

    doc = {
        "sys_id": "d1",
        "sys_effectivePermissions": ["Read", "ManageSecurity"],
        "sys_effectiveAcl": [
            {"permission": "Read", "granted": True, "status": "EFFECTIVE", "group": {"id": "g1", "name": "sales"}},
            {"permission": "Write", "granted": True, "status": "EFFECTIVE", "group": {"id": "g1", "name": "sales"}},
            {"permission": "Read", "granted": True, "status": "EFFECTIVE", "end": "2026-10-28T19:00:00Z",
             "user": {"id": "u1", "username": "cory"}},
            {"permission": "Read", "granted": True, "status": "EFFECTIVE", "end": "2026-10-28T18:30:00Z",
             "user": {"id": "u2", "username": "erin"}},
            {"permission": "Read", "granted": True, "status": "ARCHIVED", "end": "2026-10-28T10:00:00Z",
             "user": {"id": "u3", "username": "fiona"}},
            {"permission": "Read", "granted": True, "status": "PENDING", "group": {"id": "g2", "name": "hr"}},
        ],
    }

    access = summarize(doc)["access"]

    assert access["sharedWith"] == [
        {"kind": "group", "name": "sales"},
        {"kind": "user", "name": "cory"},
        {"kind": "user", "name": "erin"},
    ]
    assert access["expiresAt"] == "2026-10-28T18:30:00Z"


def test_summarize_hides_sharing_from_non_managers() -> None:
    from app.library import summarize

    access = summarize({"sys_id": "d1", "sys_effectivePermissions": ["Read"]})["access"]

    assert access == {"mine": "read", "sharedWith": None, "expiresAt": None}

@respx.mock
def test_upload_sends_bytes_then_creates_sysfile_with_blob(client: TestClient) -> None:
    _authenticate(client)
    upload = respx.post("http://openarch.test/api/upload").mock(
        return_value=httpx.Response(201, json={"id": "upl1"})
    )
    create = respx.post(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "doc1"}))
    attach = respx.put("http://openarch.test/api/documents/doc1")
    fetch = respx.get("http://openarch.test/api/documents/doc1").mock(
        return_value=httpx.Response(200, json={"sys_id": "doc1", "sys_title": "a.pdf"})
    )

    response = client.post(
        "/api/documents",
        files={"file": ("a.pdf", b"%PDF-1.4 data", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["sys_id"] == "doc1"
    assert upload.called and create.called and fetch.called
    assert not attach.called
    posts = [c.request.url.path for c in respx.calls if c.request.method == "POST"]
    assert posts == ["/api/upload", f"/api/documents/{ROOT_ID}"]
    assert json.loads(create.calls.last.request.read()) == {
        "sys_primaryType": "SysFile",
        "sys_title": "a.pdf",
        "sys_name": "a.pdf",
        "sysfile_blob": {"uploadId": "upl1"},
    }


@respx.mock
def test_failed_upload_creates_no_document(client: TestClient) -> None:
    _authenticate(client)
    respx.post("http://openarch.test/api/upload").mock(return_value=httpx.Response(500))
    create = respx.post(ROOT)

    response = client.post(
        "/api/documents",
        files={"file": ("a.pdf", b"%PDF-1.4 data", "application/pdf")},
    )

    assert response.status_code >= 400
    assert not create.called


@respx.mock
def test_unsupported_extension_is_rejected(client: TestClient) -> None:
    _authenticate(client)
    response = client.post(
        "/api/documents",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 415


@respx.mock
def test_empty_file_is_rejected(client: TestClient) -> None:
    _authenticate(client)
    response = client.post("/api/documents", files={"file": ("a.txt", b"", "text/plain")})
    assert response.status_code == 400


@respx.mock
def test_get_document_returns_raw_dto(client: TestClient) -> None:
    _authenticate(client)
    respx.get("http://openarch.test/api/documents/doc1").mock(
        return_value=httpx.Response(200, json={"sys_id": "doc1", "custom_prop": "v"})
    )
    assert client.get("/api/documents/doc1").json()["custom_prop"] == "v"


@respx.mock
def test_effective_acl_is_proxied(client: TestClient) -> None:
    _authenticate(client)
    respx.get("http://openarch.test/api/documents/doc1/fulleffectiveacl").mock(
        return_value=httpx.Response(200, json={"acl": []})
    )
    assert client.get("/api/documents/doc1/acl").status_code == 200


@respx.mock
def test_content_download_returns_bytes_and_type(client: TestClient) -> None:
    _authenticate(client)
    respx.get("http://openarch.test/api/download/doc1/sysfile_blob").mock(
        return_value=httpx.Response(200, content=b"%PDF-bytes", headers={"content-type": "application/pdf"})
    )
    response = client.get("/api/documents/doc1/content")
    assert response.status_code == 200
    assert response.content == b"%PDF-bytes"
    assert response.headers["content-type"] == "application/pdf"


@respx.mock
def test_forbidden_browse_maps_to_403(client: TestClient) -> None:
    _authenticate(client)
    respx.post(QUERY).mock(return_value=httpx.Response(403))
    assert client.get("/api/documents").status_code == 403


def test_browse_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/documents").status_code == 401


@respx.mock
def test_delete_removes_document_and_evicts_graph(client: TestClient) -> None:
    _authenticate(client)
    delete = respx.delete("http://openarch.test/api/documents/doc1").mock(
        return_value=httpx.Response(204)
    )
    # Seed a graph for the doc so we can assert eviction.
    from app.graph import DocGraph

    client.app.state.graph.store.put("doc1", DocGraph(entities={"acme": {"label": "Acme", "type": "Organization"}}))

    response = client.delete("/api/documents/doc1")

    assert response.status_code == 204
    assert delete.called
    assert client.app.state.graph.store.get("doc1") is None
