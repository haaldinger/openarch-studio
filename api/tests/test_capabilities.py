"""Capability ledger: unambiguous native-vs-extension ownership."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.capabilities import EXTENSION_OWNERS, NATIVE_OWNER


def test_capabilities_shape_is_complete(client: TestClient) -> None:
    body = client.get("/api/capabilities").json()
    for group in ("native", "extensions"):
        assert body[group]
        for item in body[group]:
            assert item["name"] and item["owner"] and item["description"] and item["evidence"]
    assert body["provenanceFlow"][0] == "Question"
    assert body["runtimes"]


def test_capability_ownership_is_unambiguous(client: TestClient) -> None:
    body = client.get("/api/capabilities").json()
    # Native capabilities are owned by OpenArch and nothing else.
    assert {c["owner"] for c in body["native"]} == {NATIVE_OWNER}
    # Extensions never claim native status.
    for ext in body["extensions"]:
        assert ext["owner"] != NATIVE_OWNER
        assert ext["owner"] in EXTENSION_OWNERS


def test_extraction_capabilities_name_docling(client: TestClient) -> None:
    body = client.get("/api/capabilities").json()
    by_name = {e["name"]: e for e in body["extensions"]}
    for name in ("Scanned-image OCR", "Text & metadata extraction"):
        assert by_name[name]["owner"] == "Studio + Docling (Tika fallback)"
        assert by_name[name]["evidence"] == "extraction.py"
    assert any(r["name"] == "Docling" for r in body["runtimes"])
