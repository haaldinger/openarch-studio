"""Chat route: streams a permission-aware, cited answer as Server-Sent Events."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent import AgentService, sse
from .auth import current_credentials
from .enrichment import EnrichmentService
from .models import Credentials

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []
    sessionId: str | None = None
    scope: str | None = None  # folder id; restricts retrieval to that subtree


def get_agent(request: Request) -> AgentService:
    enrichment: EnrichmentService = request.app.state.enrichment
    return AgentService(request.app.state.settings, enrichment)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    agent: AgentService = Depends(get_agent),
    credentials: Credentials = Depends(current_credentials),
) -> StreamingResponse:
    evidence = await agent.retrieve(body.question, credentials, scope=body.scope)
    evidence = await agent.verify(evidence, credentials)
    history = [m.model_dump() for m in body.history]

    async def events() -> AsyncIterator[str]:
        yield sse("retrieval", {"count": len(evidence)})
        try:
            async for token in agent.stream_answer(body.question, history, evidence):
                yield sse("token", {"token": token})
        except Exception as exc:  # noqa: BLE001 - surfaced to the client, retrieval preserved
            yield sse("error", {"message": str(exc)})
            return
        yield sse(
            "citations",
            {
                "citations": [
                    {"docId": e.doc_id, "chunkId": e.chunk_id, "snippet": e.text, "score": e.score}
                    for e in evidence
                ]
            },
        )
        yield sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream")
