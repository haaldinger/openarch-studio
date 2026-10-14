"""Knowledge-graph routes."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request, status

from .auth import current_credentials, get_openarch_client
from .enrichment import EnrichmentService
from .graph import GraphService
from .models import Credentials
from .openarch import OpenArchClient

router = APIRouter(prefix="/api")


def get_graph(request: Request) -> GraphService:
    return request.app.state.graph


def get_enrichment(request: Request) -> EnrichmentService:
    return request.app.state.enrichment


@router.get("/graph")
async def full_graph(
    scope: str | None = None,
    service: GraphService = Depends(get_graph),
    credentials: Credentials = Depends(current_credentials),
) -> dict[str, Any]:
    return await service.merged(credentials, scope=scope)


@router.post("/documents/{doc_id}/graph", status_code=status.HTTP_200_OK)
async def extract_graph(
    doc_id: str,
    service: GraphService = Depends(get_graph),
    enrichment: EnrichmentService = Depends(get_enrichment),
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    # Build the graph from chunk text already stored in OpenArch (no re-OCR).
    texts = await client.fetch_chunk_texts(doc_id)
    text = "\n".join(t for t in texts if t)
    if not text:
        content, mime = await client.download(doc_id)
        text = await enrichment.extract_text(content, mime)
    try:
        graph = await service.extract(doc_id, text)
    except httpx.HTTPError:
        # Model slow/unavailable: report an empty graph rather than failing the request.
        from .graph import DocGraph

        graph = DocGraph()
    return {
        "nodes": [
            {"id": nid, "label": m["label"], "type": m["type"]} for nid, m in graph.entities.items()
        ],
        "edges": [{"source": s, "target": t, "type": ty} for s, t, ty in graph.relations],
    }
