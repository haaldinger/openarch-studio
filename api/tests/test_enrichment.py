"""Enrichment pipeline: extract -> chunk -> embed -> SysEmbeddings, with failures."""

from __future__ import annotations

import io
import json

import httpx
import pyarrow.parquet as pq
import respx

from app.config import Settings
from app.enrichment import EnrichmentService, Job
from app.extraction import PAGE_BREAK
from app.fields import FieldsService
from app.models import Credentials

DOC = "doc1"
OA = "http://openarch.test"
TIKA = "http://tika.test/tika"
DOCLING = "http://docling.test/v1/convert/file"
EMBED = "http://model.test/v1/embeddings"
CHAT = "http://model.test/v1/chat/completions"


def make_service(extractor: str = "tika", with_fields: bool = False) -> EnrichmentService:
    settings = Settings(
        openarch_url=OA,
        tika_url="http://tika.test",
        docling_url="http://docling.test",
        model_base_url="http://model.test/v1",
        embedding_model="nomic-embed-text",
        extractor=extractor,
    )
    return EnrichmentService(
        settings, fields=FieldsService(settings) if with_fields else None
    )


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
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one.\n\n## Next\n\nPara two."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        )
    )
    _mock_openarch_write()

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"ignored by tika mock", mime="text/plain")

    assert job.state == "complete"
    assert [s.name for s in job.stages][-1] == "classified"
    assert [s.status for s in job.stages] == ["done"] * 6
    assert job.stage("embedded").detail == "2 vectors"


def _mock_pipeline_inputs() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Invoice from Acme."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
    )
    respx.post(f"{OA}/api/query").mock(return_value=httpx.Response(200, json={"documents": []}))
    _mock_openarch_write()


def _model_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def _run_with_fields() -> Job:
    service = make_service(with_fields=True)
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")
    return job


@respx.mock
async def test_classified_stage_records_type_and_count() -> None:
    _mock_pipeline_inputs()
    respx.post(CHAT).mock(
        return_value=_model_reply('{"type": "invoice", "fields": {"vendor": "Acme", "total": "12.50"}}')
    )

    job = await _run_with_fields()

    assert job.state == "complete"
    assert job.stage("classified").status == "done"
    assert job.stage("classified").detail == "invoice · 2 fields"


@respx.mock
async def test_classification_failure_keeps_job_complete() -> None:
    _mock_pipeline_inputs()
    respx.post(CHAT).mock(return_value=httpx.Response(500))

    job = await _run_with_fields()

    assert job.state == "complete"
    assert job.stage("indexed").status == "done"
    assert job.stage("classified").status == "failed"
    assert job.stage("classified").detail


@respx.mock
async def test_invalid_model_json_detail() -> None:
    _mock_pipeline_inputs()
    respx.post(CHAT).mock(return_value=_model_reply("not json"))

    job = await _run_with_fields()

    assert job.state == "complete"
    assert job.stage("classified").status == "failed"
    assert job.stage("classified").detail == "model returned invalid JSON"


@respx.mock
async def test_no_write_permission_message() -> None:
    _mock_pipeline_inputs()
    respx.post(CHAT).mock(return_value=_model_reply('{"type": "invoice", "fields": {"a": "b"}}'))
    # The first PUT is the embeddings mixin; the classification write is the second.
    respx.put(f"{OA}/api/documents/{DOC}").mock(
        side_effect=[httpx.Response(200, json={}), httpx.Response(403)]
    )

    job = await _run_with_fields()

    assert job.state == "complete"
    assert job.stage("classified").status == "failed"
    assert job.stage("classified").detail == "no write permission on this document"


@respx.mock
async def test_without_fields_service_stage_is_skipped() -> None:
    _mock_pipeline_inputs()

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "complete"
    assert job.stage("classified").status == "done"
    assert job.stage("classified").detail == "skipped"


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
    job = service.store.create(DOC, "a.pdf", "admin")
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
    job = service.store.create(DOC, "a.pdf", "admin")
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
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.stage("extracted").detail == "Tika · 9 chars"


@respx.mock
async def test_extraction_failure_fails_that_stage() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(500))
    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
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
    job = service.store.create(DOC, "a.pdf", "admin")
    await service.run(job, creds(), content=b"not really a pdf", mime="application/pdf")

    assert job.state == "failed"
    assert job.stage("chunked").status == "failed"
    assert not delete.called


@respx.mock
async def test_embedding_count_mismatch_fails_before_write() -> None:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Para one.\n\n## Next\n\nPara two."))
    # Two chunks but only one embedding returned.
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    upload = respx.post(f"{OA}/api/upload").mock(return_value=httpx.Response(201, json={"id": "x"}))

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
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
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds())  # no content -> triggers download

    assert job.state == "complete"


def _mock_pipeline_with_children(existing: list[str]) -> tuple[respx.Route, respx.Route]:
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="Invoice from Acme."))
    respx.post(EMBED).mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
    )
    _mock_openarch_write()
    query = respx.post(f"{OA}/api/query").mock(
        return_value=httpx.Response(
            200, json={"documents": [{"sys_id": i} for i in [*existing, "child"]]}
        )
    )
    delete = respx.delete(url__regex=rf"{OA}/api/documents/.+").mock(
        return_value=httpx.Response(204)
    )
    return query, delete


@respx.mock
async def test_re_enrichment_deletes_older_embeddings_children_but_not_the_new_one() -> None:
    query, delete = _mock_pipeline_with_children(["old1", "old2"])

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "complete"
    assert json.loads(query.calls.last.request.content)["query"] == (
        f"SELECT * FROM SysEmbeddings WHERE sys_parentId = '{DOC}'"
    )
    assert sorted(c.request.url.path for c in delete.calls) == [
        "/api/documents/old1",
        "/api/documents/old2",
    ]


@respx.mock
async def test_first_enrichment_deletes_nothing() -> None:
    _, delete = _mock_pipeline_with_children([])

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "complete" and not delete.called


@respx.mock
async def test_cleanup_failure_leaves_job_complete() -> None:
    _, delete = _mock_pipeline_with_children(["old1", "old2"])
    delete.mock(side_effect=[httpx.Response(500), httpx.Response(204)])

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "complete"
    assert [s.status for s in job.stages] == ["done"] * 6
    assert len(delete.calls) == 2  # a failed delete doesn't stop the rest


@respx.mock
async def test_cleanup_query_failure_leaves_job_complete() -> None:
    query, delete = _mock_pipeline_with_children(["old1"])
    query.mock(return_value=httpx.Response(500))

    service = make_service()
    job = service.store.create(DOC, "a.txt", "admin")
    await service.run(job, creds(), content=b"x", mime="text/plain")

    assert job.state == "complete" and not delete.called


def test_embedding_type_is_sanitized() -> None:
    service = make_service()
    assert service.embedding_type() == "nomic-embed-text"
