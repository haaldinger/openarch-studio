"""Enrichment pipeline: extract -> chunk -> embed -> SysEmbeddings, with failures."""

from __future__ import annotations

import io

import httpx
import pyarrow.parquet as pq
import respx

from app.config import Settings
from app.enrichment import EnrichmentService
from app.extraction import PAGE_BREAK
from app.models import Credentials

DOC = "doc1"
OA = "http://openarch.test"
TIKA = "http://tika.test/tika"
DOCLING = "http://docling.test/v1/convert/file"
EMBED = "http://model.test/v1/embeddings"


def make_service(extractor: str = "tika") -> EnrichmentService:
    settings = Settings(
        openarch_url=OA,
        tika_url="http://tika.test",
        docling_url="http://docling.test",
        model_base_url="http://model.test/v1",
        embedding_model="nomic-embed-text",
        extractor=extractor,
    )
    return EnrichmentService(settings)


def creds() -> Credentials:
    return Credentials(username="admin", password="p")


def _mock_openarch_write() -> None:
    respx.get(f"{OA}/api/documents/{DOC}").mock(
        return_value=httpx.Response(200, json={"sys_id": DOC, "sys_mixinTypes": []})
    )
    respx.put(f"{OA}/api/documents/{DOC}").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "upl"}))
    respx.post(f"{OA}/api/documents/{DOC}").mock(
        return_value=httpx.Response(200, json={"sys_id": "child"})
    )
    respx.get(f"{OA}/api/query/waitForFullTextSearchIndexing").mock(
        return_value=httpx.Response(200, json={"indexing": "done"})
    )


@respx.mock
async def test_happy_path_completes_all_stages() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one.\n\nPara two."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        )
    )
    _mock_openarch_write()

    service = make_service()
    job = service.store.create(DOC, "a.txt")
    await service.run(job, creds(), content=b"ignored by tika mock", mime="text/plain")

    assert job.state == "complete"
    assert [s.status for s in job.stages] == ["done"] * 5
    assert job.stage("embedded").detail == "2 vectors"


@respx.mock
async def test_docling_pages_reach_parquet_locations() -> None:
    respx.post(DOCLING).mock(
        return_value=httpx.Response(
            200,
            json={"document": {"md_content": f"Page one.{PAGE_BREAK}Page two."}, "status": "success"},
        )
    )
    respx.post(EMBED).mock(
        return_value=httpx.Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        )
    )
    _mock_openarch_write()

    service = make_service(extractor="docling")
    job = service.store.create(DOC, "a.pdf")
    await service.run(job, creds(), content=b"%PDF", mime="application/pdf")

    assert job.state == "complete"
    assert job.stage("extracted").detail.startswith("Docling · ")
    upload = next(c for c in respx.calls if c.request.url.path == "/api/upload")
    table = pq.read_table(io.BytesIO(upload.request.content))
    pages = [row["text"]["page"] for row in table.column("location").to_pylist()]
    assert pages == [1, 2]


@respx.mock
async def test_extracted_stage_names_the_engine() -> None:
    respx.post(DOCLING).mock(return_value=httpx.Response(500))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
    )
    _mock_openarch_write()

    service = make_service(extractor="docling")
    job = service.store.create(DOC, "a.pdf")
    await service.run(job, creds(), content=b"%PDF", mime="application/pdf")

    assert job.stage("extracted").detail.startswith("Tika fallback")


@respx.mock
async def test_tika_only_stage_detail_is_plain() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
    )
    _mock_openarch_write()

    service = make_service()
    job = service.store.create(DOC, "a.txt")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.stage("extracted").detail == "Tika · 9 chars"


@respx.mock
async def test_extraction_failure_fails_that_stage() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(500))
    service = make_service()
    job = service.store.create(DOC, "a.txt")
    await service.run(job, creds(), content=b"x", mime="application/pdf")

    assert job.state == "failed"
    assert job.stage("extracted").status == "failed"
    assert job.stage("stored").status == "done"


@respx.mock
async def test_mime_mismatch_preserves_document() -> None:
    # Tika yields nothing extractable; the job fails at chunking and never deletes the source.
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="   \n\n   "))
    delete = respx.delete(f"{OA}/api/documents/{DOC}").mock(return_value=httpx.Response(204))

    service = make_service()
    job = service.store.create(DOC, "a.pdf")
    await service.run(job, creds(), content=b"not really a pdf", mime="application/pdf")

    assert job.state == "failed"
    assert job.stage("chunked").status == "failed"
    assert not delete.called


@respx.mock
async def test_embedding_count_mismatch_fails_before_write() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one.\n\nPara two."))
    # Two chunks but only one embedding returned.
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    upload = respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "x"}))

    service = make_service()
    job = service.store.create(DOC, "a.txt")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "failed"
    assert job.stage("embedded").status == "failed"
    assert not upload.called  # nothing written to OpenArch on a bad embedding batch


@respx.mock
async def test_retry_redownloads_source_from_openarch() -> None:
    # With no content passed, the service pulls the binary back from OpenArch.
    respx.get(f"{OA}/api/download/{DOC}/sysfile_blob").mock(
        return_value=httpx.Response(200, content=b"text", headers={"content-type": "text/plain"})
    )
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Only one paragraph."))
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]}))
    _mock_openarch_write()

    service = make_service()
    job = service.store.create(DOC, "a.txt")
    await service.run(job, creds())  # no content -> triggers download

    assert job.state == "complete"


def test_embedding_type_is_sanitized() -> None:
    service = make_service()
    assert service.embedding_type() == "nomic-embed-text"
