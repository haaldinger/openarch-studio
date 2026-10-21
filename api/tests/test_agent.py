"""Agent: ACL-filtered retrieval, citation verification, grounded streaming."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.agent import INSUFFICIENT, AgentService, Evidence
from app.config import Settings
from app.enrichment import EnrichmentService
from app.models import Credentials

OA = "http://openarch.test"
EMBED = "http://model.test/v1/embeddings"
CHAT = "http://model.test/v1/chat/completions"
VECTOR_QUERY = f"{OA}/api/query/embeddings"
ROOT = f"{OA}/api/documents/00000000-0000-0000-0000-000000000000"


def make_agent() -> AgentService:
    settings = Settings(
        openarch_url=OA,
        model_base_url="http://model.test/v1",
        embedding_model="nomic-embed-text",
        chat_model="llama3.1",
    )
    return AgentService(settings, EnrichmentService(settings))


def creds() -> Credentials:
    return Credentials(username="admin", password="p")


@respx.mock
async def test_retrieve_runs_as_user_and_maps_hits() -> None:
    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(f"{OA}/api/query").mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    route = respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={
                "embeddings": [
                    {"sysembed_docId": "d1", "sysembed_id": "c1", "sysembed_text": "txt", "sysembed_score": 0.8}
                ]
            },
        )
    )
    evidence = await make_agent().retrieve("q", creds())
    assert evidence == [Evidence(doc_id="d1", chunk_id="c1", text="txt", score=0.8)]
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")


@respx.mock
async def test_verify_drops_now_forbidden_documents() -> None:
    respx.get(f"{OA}/api/documents/ok").mock(return_value=httpx.Response(200, json={"sys_id": "ok"}))
    respx.get(f"{OA}/api/documents/gone").mock(return_value=httpx.Response(403))
    evidence = [
        Evidence("ok", "c1", "visible", 0.9),
        Evidence("gone", "c2", "secret", 0.8),
    ]
    kept = await make_agent().verify(evidence, creds())
    assert [e.doc_id for e in kept] == ["ok"]


async def test_no_evidence_yields_insufficiency() -> None:
    tokens = [t async for t in make_agent().stream_answer("q", [], [])]
    assert tokens == [INSUFFICIENT]


@respx.mock
async def test_stream_answer_emits_model_tokens() -> None:
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(CHAT).mock(return_value=httpx.Response(200, text=sse_body))
    evidence = [Evidence("d1", "c1", "ctx", 0.9)]
    tokens = [t async for t in make_agent().stream_answer("q", [], evidence)]
    assert "".join(tokens) == "Hello world"


def test_prompt_marks_context_untrusted() -> None:
    messages = make_agent()._messages("q", [], [Evidence("d1", "c1", "ctx", 0.9)])
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    assert "untrusted" in system.lower()
    assert "[c1] ctx" in system


@respx.mock
def test_chat_route_streams_sse_with_citations(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    client.post("/api/session", json={"username": "admin", "password": "p"})

    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(f"{OA}/api/query").mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [{"sysembed_docId": "d1", "sysembed_id": "c1", "sysembed_text": "ctx"}]},
        )
    )
    respx.get(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(200, json={"sys_id": "d1"}))
    respx.post(CHAT).mock(
        return_value=httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Answer"}}]}\n\ndata: [DONE]\n\n')
    )

    response = client.post("/api/chat", json={"question": "what?"})
    assert response.status_code == 200
    body = response.text
    # AG-UI shaped lifecycle: the run opens before retrieval, so the client can
    # show the search happening instead of waiting on a blocked stream.
    assert body.index("event: RUN_STARTED") < body.index("event: TOOL_CALL_START")
    assert body.index("event: TOOL_CALL_START") < body.index("event: TOOL_CALL_END")
    assert "event: TEXT_MESSAGE_CONTENT" in body
    assert "event: STATE_SNAPSHOT" in body and '"docId": "d1"' in body
    assert "event: RUN_FINISHED" in body


@respx.mock
def test_chat_emits_a2ui_surface_for_citations(client: TestClient) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json={"sys_id": "root"}))
    client.post("/api/session", json={"username": "admin", "password": "p"})

    respx.post(EMBED).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    respx.post(f"{OA}/api/query").mock(return_value=httpx.Response(200, json={"documents": [{"sys_id": "d1"}]}))
    respx.post(VECTOR_QUERY).mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [{"sysembed_docId": "d1", "sysembed_id": "c1", "sysembed_text": "ctx"}]},
        )
    )
    respx.get(f"{OA}/api/documents/d1").mock(return_value=httpx.Response(200, json={"sys_id": "d1"}))
    respx.post(CHAT).mock(
        return_value=httpx.Response(200, text='data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]\n\n')
    )

    body = client.post("/api/chat", json={"question": "what?"}).text
    assert "event: CUSTOM" in body and '"name": "a2ui"' in body
    # v0.9 requires the surface to be created after its components and data.
    assert body.index("updateComponents") < body.index("createSurface")


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/chat", json={"question": "x"}).status_code == 401
