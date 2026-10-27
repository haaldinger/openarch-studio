"""Chat route: streams a permission-aware, cited answer as AG-UI shaped events.

Retrieval runs *inside* the stream so the client can show it happening, and the
verified citations are additionally offered as an A2UI surface that the client
renders with its own components.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import a2ui, agui
from .agent import AgentService
from .auth import current_credentials
from .config import Settings
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
    return AgentService(request.app.state.settings, enrichment, request.app.state.reranker)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/chat")
async def chat(
    body: ChatRequest,
    agent: AgentService = Depends(get_agent),
    credentials: Credentials = Depends(current_credentials),
    settings: Settings = Depends(get_settings_dep),
) -> StreamingResponse:
    history = [m.model_dump() for m in body.history]
    run_id = uuid4().hex

    async def events() -> AsyncIterator[str]:
        yield agui.event(
            agui.RUN_STARTED, {"runId": run_id, "threadId": body.sessionId or run_id}
        )

        tool_call_id = uuid4().hex
        yield agui.event(
            agui.TOOL_CALL_START,
            {"toolCallId": tool_call_id, "toolCallName": "search_documents"},
        )
        titles: dict[str, str] = {}
        try:
            found, rerank_status = await agent.retrieve(
                body.question, credentials, scope=body.scope
            )
            evidence = await agent.verify(found, credentials, titles)
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as a run error
            yield agui.event(agui.RUN_ERROR, {"runId": run_id, "message": str(exc)})
            return
        yield agui.event(
            agui.TOOL_CALL_END,
            {
                "toolCallId": tool_call_id,
                "result": {
                    "retrieved": len(found),
                    "readable": len(evidence),
                    "rerank": rerank_status,
                },
            },
        )

        message_id = uuid4().hex
        yield agui.event(
            agui.TEXT_MESSAGE_START, {"messageId": message_id, "role": "assistant"}
        )
        answer = ""
        try:
            async for token in agent.stream_answer(body.question, history, evidence):
                answer += token
                yield agui.event(
                    agui.TEXT_MESSAGE_CONTENT, {"messageId": message_id, "delta": token}
                )
        except Exception as exc:  # noqa: BLE001 - retrieval is preserved for a retry
            yield agui.event(agui.RUN_ERROR, {"runId": run_id, "message": str(exc)})
            return
        yield agui.event(agui.TEXT_MESSAGE_END, {"messageId": message_id})

        citations: list[dict[str, Any]] = [
            {
                "docId": e.doc_id,
                "chunkId": e.chunk_id,
                "snippet": e.text,
                "score": e.score,
                "vectorScore": e.vector_score,
                "page": e.page,
                "title": titles.get(e.doc_id, e.doc_id),
            }
            for e in evidence
        ]
        yield agui.event(agui.STATE_SNAPSHOT, {"snapshot": {"citations": citations}})

        if settings.a2ui_enabled and citations:
            # One row per document: several chunks of the same file are one source.
            by_document: dict[str, dict[str, Any]] = {}
            for citation in citations:
                by_document.setdefault(citation["docId"], citation)
            sources = list(by_document.values())

            kind, questions = await agent.plan_surface(body.question, answer, len(sources))
            surface_id = f"{kind}-{run_id}"
            if kind == "compare" and len(sources) > 1:
                surface = a2ui.comparison_surface(surface_id, sources)
            elif kind == "followups":
                surface = a2ui.followups_surface(surface_id, questions)
            else:
                surface = a2ui.sources_surface(surface_id, sources)

            yield agui.event(agui.CUSTOM, {"name": "a2ui", "value": surface})

        yield agui.event(agui.RUN_FINISHED, {"runId": run_id})

    return StreamingResponse(events(), media_type="text/event-stream")
