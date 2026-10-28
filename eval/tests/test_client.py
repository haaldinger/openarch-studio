import json
from pathlib import Path

import httpx
import pytest
import respx

from studio_eval.client import Citation, ChatResult, StudioClient, StudioError, parse_chat_stream

BASE = "http://studio.test"
ROOT = "00000000-0000-0000-0000-000000000000"


def sse(event_type: str, /, **payload) -> list[str]:
    return [f"event: {event_type}", f"data: {json.dumps({'type': event_type, **payload})}", ""]


def stream(*events: list[str]) -> list[str]:
    return [line for e in events for line in e]


def test_parse_chat_stream_full_run():
    citations = [
        {"docId": "d1", "chunkId": "c1", "snippet": "Total 100", "score": 0.9,
         "vectorScore": 0.5, "page": 2, "title": "a.tif"},
        {"docId": "d2", "chunkId": "c2", "snippet": "Other", "score": None,
         "vectorScore": None, "page": 1, "title": "b.tif"},
    ]
    lines = stream(
        sse("RUN_STARTED", runId="r"),
        sse("TOOL_CALL_START", toolCallId="t", toolCallName="search_documents"),
        sse("TOOL_CALL_END", toolCallId="t", result={"retrieved": 2, "readable": 2, "rerank": "reranked"}),
        sse("TEXT_MESSAGE_START", messageId="m", role="assistant"),
        sse("TEXT_MESSAGE_CONTENT", messageId="m", delta="The total "),
        sse("TEXT_MESSAGE_CONTENT", messageId="m", delta="is 100."),
        sse("TEXT_MESSAGE_END", messageId="m"),
        sse("STATE_SNAPSHOT", snapshot={"citations": citations}),
        sse("CUSTOM", name="a2ui", value={}),
        sse("RUN_FINISHED", runId="r"),
    )
    got = parse_chat_stream(lines)
    assert got == ChatResult(
        answer="The total is 100.",
        citations=[
            Citation("d1", "a.tif", 2, "Total 100", 0.9, 0.5),
            Citation("d2", "b.tif", 1, "Other", None, None),
        ],
        rerank="reranked",
        error=None,
    )


def test_parse_chat_stream_run_error_sets_error():
    lines = stream(
        sse("RUN_STARTED", runId="r"),
        sse("TOOL_CALL_END", toolCallId="t", result={"rerank": "skipped (down)"}),
        sse("RUN_ERROR", runId="r", message="model unavailable"),
    )
    got = parse_chat_stream(lines)
    assert got.error == "model unavailable"
    assert got.rerank == "skipped (down)"
    assert got.answer == ""
    assert got.citations == []


def test_parse_chat_stream_ignores_noise():
    lines = [": keepalive", "", "data: not json", *sse("TEXT_MESSAGE_CONTENT", delta="hi")]
    assert parse_chat_stream(lines).answer == "hi"


@pytest.fixture
def client():
    with StudioClient(BASE, "alice", "pw") as c:
        yield c


@respx.mock
def test_login_posts_credentials(client):
    route = respx.post(f"{BASE}/api/session").mock(
        return_value=httpx.Response(200, json={"username": "alice"})
    )
    client.login()
    assert json.loads(route.calls[0].request.content) == {"username": "alice", "password": "pw"}


@respx.mock
def test_login_401(client):
    respx.post(f"{BASE}/api/session").mock(return_value=httpx.Response(401))
    with pytest.raises(StudioError, match="sign-in failed for user alice"):
        client.login()


@respx.mock
def test_unreachable(client):
    respx.post(f"{BASE}/api/session").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(StudioError, match="cannot reach Studio at http://studio.test"):
        client.login()


@respx.mock
def test_ask_streams_and_sends_scope(client):
    body = "\n".join(
        stream(
            sse("TEXT_MESSAGE_CONTENT", delta="ok"),
            sse("STATE_SNAPSHOT", snapshot={"citations": []}),
        )
    )
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    got = client.ask("Q?", "folder-1")
    assert got.answer == "ok"
    assert json.loads(route.calls[0].request.content) == {"question": "Q?", "scope": "folder-1"}


@respx.mock
def test_ask_403_mentions_baseline(client):
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(403))
    with pytest.raises(StudioError, match="baseline mode"):
        client.ask("Q?", "f")


@respx.mock
def test_ask_401(client):
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(401))
    with pytest.raises(StudioError, match="sign-in expired"):
        client.ask("Q?", "f")


@respx.mock
def test_ensure_folder_reuses_existing(client):
    list_route = respx.get(f"{BASE}/api/documents", params={"parentId": ROOT}).mock(
        return_value=httpx.Response(
            200,
            json={"parentId": ROOT, "documents": [
                {"id": "x", "title": "Eval corpus 2", "isFolderish": True},
                {"id": "f1", "title": "Eval corpus", "isFolderish": True},
            ]},
        )
    )
    create = respx.post(f"{BASE}/api/folders").mock(return_value=httpx.Response(201, json={}))
    assert client.ensure_folder("Eval corpus") == "f1"
    assert list_route.called and not create.called


@respx.mock
def test_ensure_folder_ignores_non_folder_with_same_title(client):
    respx.get(f"{BASE}/api/documents").mock(
        return_value=httpx.Response(
            200, json={"documents": [{"id": "d", "title": "Eval corpus", "isFolderish": False}]}
        )
    )
    create = respx.post(f"{BASE}/api/folders").mock(
        return_value=httpx.Response(201, json={"sys_id": "new"})
    )
    assert client.ensure_folder("Eval corpus") == "new"
    assert json.loads(create.calls[0].request.content) == {"title": "Eval corpus"}


@respx.mock
def test_extracted_text_groups_by_page(client):
    def hit(text, page=None):
        h = {"sysembed_text": text}
        if page is not None:
            h["sysembed_location"] = {"text": {"page": page}}
        return h

    route = respx.get(f"{BASE}/api/documents/d1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={"docId": "d1", "count": 4, "raw": [
                hit("a", 1), hit("b", 1), hit("c", 2), hit("legacy"),
            ]},
        )
    )
    assert client.extracted_text("d1") == {1: "a\n\nb\n\nlegacy", 2: "c"}
    assert route.calls[0].request.url.params["raw"] == "true"


# --- ensure_corpus -------------------------------------------------------

class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s


def job(job_id, doc_id, filename, state="running", stages=None, error=None):
    return {"id": job_id, "docId": doc_id, "filename": filename, "state": state,
            "error": error, "stages": stages or []}


@pytest.fixture
def samples(tmp_path: Path) -> Path:
    d = tmp_path / "samples"
    d.mkdir()
    for name in ("b.tif", "a.tif", "c.tif"):
        (d / name).write_bytes(b"img-" + name.encode())
    return d


def folder_listing(*names):
    return httpx.Response(
        200,
        json={"parentId": "F", "documents": [
            {"id": f"id-{n}", "title": n, "name": n, "isFolderish": False} for n in names
        ]},
    )


@respx.mock
def test_ensure_corpus_uploads_only_missing_and_waits(samples):
    respx.get(f"{BASE}/api/documents", params={"parentId": "F"}).mock(
        return_value=folder_listing("c.tif")
    )
    uploads = []

    def upload(request: httpx.Request):
        body = request.content
        name = "a.tif" if b'filename="a.tif"' in body else "b.tif"
        uploads.append(name)
        return httpx.Response(
            201, json={"sys_id": f"id-{name}", "_studioJobId": f"job-{name}"}
        )

    up = respx.post(f"{BASE}/api/documents", params={"parentId": "F"}).mock(side_effect=upload)
    polls = iter([
        {"jobs": [job("job-a.tif", "id-a.tif", "a.tif"), job("job-b.tif", "id-b.tif", "b.tif", "complete"),
                  job("old", "x", "old.tif", "failed")]},
        {"jobs": [job("job-a.tif", "id-a.tif", "a.tif", "complete"),
                  job("job-b.tif", "id-b.tif", "b.tif", "complete")]},
    ])
    jobs_route = respx.get(f"{BASE}/api/jobs").mock(
        side_effect=lambda r: httpx.Response(200, json=next(polls))
    )
    t = FakeTime()
    with StudioClient(BASE, "u", "p", sleep=t.sleep, clock=t.clock) as c:
        got = c.ensure_corpus("F", samples, timeout_s=60, poll_s=5)

    assert uploads == ["a.tif", "b.tif"]
    assert up.call_count == 2
    assert jobs_route.call_count == 2
    assert t.now == 5
    assert got == {"a.tif": "id-a.tif", "b.tif": "id-b.tif", "c.tif": "id-c.tif"}


@respx.mock
def test_ensure_corpus_skips_everything_when_present(samples):
    respx.get(f"{BASE}/api/documents", params={"parentId": "F"}).mock(
        return_value=folder_listing("a.tif", "b.tif", "c.tif", "extra.pdf")
    )
    up = respx.post(f"{BASE}/api/documents").mock(return_value=httpx.Response(201, json={}))
    jobs_route = respx.get(f"{BASE}/api/jobs").mock(return_value=httpx.Response(200, json={"jobs": []}))
    with StudioClient(BASE, "u", "p") as c:
        got = c.ensure_corpus("F", samples)
    assert set(got) == {"a.tif", "b.tif", "c.tif"}
    assert not up.called and not jobs_route.called


@respx.mock
def test_ensure_corpus_failed_job_names_file_and_stage(samples):
    respx.get(f"{BASE}/api/documents").mock(return_value=folder_listing("a.tif", "c.tif"))
    respx.post(f"{BASE}/api/documents").mock(
        return_value=httpx.Response(201, json={"sys_id": "id-b", "_studioJobId": "jb"})
    )
    stages = [
        {"name": "stored", "status": "done", "detail": ""},
        {"name": "extracted", "status": "failed", "detail": "tika timeout"},
        {"name": "chunked", "status": "pending", "detail": ""},
    ]
    respx.get(f"{BASE}/api/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [job("jb", "id-b", "b.tif", "failed", stages)]})
    )
    t = FakeTime()
    with StudioClient(BASE, "u", "p", sleep=t.sleep, clock=t.clock) as c:
        with pytest.raises(StudioError) as exc:
            c.ensure_corpus("F", samples)
    msg = str(exc.value)
    assert "b.tif" in msg and "extracted" in msg and "tika timeout" in msg


@respx.mock
def test_ensure_corpus_timeout_names_pending_files(samples):
    respx.get(f"{BASE}/api/documents").mock(return_value=folder_listing("c.tif"))
    respx.post(f"{BASE}/api/documents").mock(
        side_effect=lambda r: httpx.Response(
            201,
            json={"sys_id": "i", "_studioJobId": "ja" if b'filename="a.tif"' in r.content else "jb"},
        )
    )
    respx.get(f"{BASE}/api/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [
            job("ja", "i", "a.tif"), job("jb", "i", "b.tif", "complete"),
        ]})
    )
    t = FakeTime()
    with StudioClient(BASE, "u", "p", sleep=t.sleep, clock=t.clock) as c:
        with pytest.raises(StudioError, match=r"timed out.*a\.tif") as exc:
            c.ensure_corpus("F", samples, timeout_s=12, poll_s=5)
    assert "b.tif" not in str(exc.value)
    assert t.now >= 12


@respx.mock
def test_ensure_corpus_classified_failure_is_not_fatal(samples):
    respx.get(f"{BASE}/api/documents").mock(return_value=folder_listing("a.tif", "c.tif"))
    respx.post(f"{BASE}/api/documents").mock(
        return_value=httpx.Response(201, json={"sys_id": "id-b", "_studioJobId": "jb"})
    )
    stages = [{"name": "classified", "status": "failed", "detail": "no permission"}]
    respx.get(f"{BASE}/api/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [job("jb", "id-b", "b.tif", "complete", stages)]})
    )
    with StudioClient(BASE, "u", "p") as c:
        assert c.ensure_corpus("F", samples)["b.tif"] == "id-b"
