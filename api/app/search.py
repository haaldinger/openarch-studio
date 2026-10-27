"""Search: keyword and advanced HXQL go straight to OpenArch; semantic adds a
Studio embedding step. Every response carries provenance naming which layer did
what, and all three run as the signed-in user so OpenArch ACLs stay in force.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from .agent import hit_page
from .auth import get_openarch_client
from .enrichment import EnrichmentService
from .library import summarize
from .openarch import (
    OpenArchClient,
    OpenArchForbidden,
    OpenArchUnavailable,
)

router = APIRouter(prefix="/api")


class SearchRequest(BaseModel):
    mode: str  # keyword | hxql | semantic
    query: str
    limit: int = 10
    scope: str | None = None  # folder id; restricts results to that subtree


def _escape(term: str) -> str:
    return term.replace("'", "''")


def get_enrichment(request: Request) -> EnrichmentService:
    return request.app.state.enrichment


@router.post("/search")
async def search(
    body: SearchRequest,
    client: OpenArchClient = Depends(get_openarch_client),
    service: EnrichmentService = Depends(get_enrichment),
) -> dict[str, Any]:
    if not body.query.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query is required")

    started = time.monotonic()
    try:
        if body.mode == "keyword":
            # OpenArch server-side fulltext isn't populated in every deployment, but Studio
            # indexes chunk text in the embeddings index — so keyword search retrieves from
            # there and keeps chunks that actually contain the term(s).
            vector = await service.embed_query(body.query)
            embedding_type = f"{service.embedding_type()}*"
            result = await client.semantic_search(
                vector, embedding_type=embedding_type, scope=body.scope, limit=50
            )
            terms = [t.lower() for t in body.query.split() if t]
            results = [
                {
                    "id": hit.get("sysembed_docId"),
                    "title": None,
                    "snippet": hit.get("sysembed_text"),
                    "score": hit.get("sysembed_score"),
                    "page": hit_page(hit),
                }
                for hit in result.get("embeddings", [])
                if any(t in (hit.get("sysembed_text") or "").lower() for t in terms)
            ][: body.limit]
            provenance = {"providedBy": "OpenArch chunk index", "extendedBy": "Studio full-text filter",
                          "requestPath": "/api/query/embeddings", "embeddingType": embedding_type}

        elif body.mode == "hxql":
            result = await client.query({"query": body.query, "limit": body.limit})
            results = [
                {"id": s["id"], "title": s["title"], "snippet": None, "score": None}
                for s in (summarize(d) for d in result.get("documents", []))
            ]
            provenance = {"providedBy": "OpenArch", "extendedBy": None,
                          "requestPath": "/api/query", "embeddingType": None}

        elif body.mode == "semantic":
            vector = await service.embed_query(body.query)
            embedding_type = f"{service.embedding_type()}*"
            result = await client.semantic_search(
                vector, embedding_type=embedding_type, scope=body.scope, limit=body.limit
            )
            results = [
                {
                    "id": hit.get("sysembed_docId"),
                    "title": None,
                    "snippet": hit.get("sysembed_text"),
                    "score": hit.get("sysembed_score"),
                    "page": hit_page(hit),
                }
                for hit in result.get("embeddings", [])
            ]
            provenance = {"providedBy": "OpenArch vector search", "extendedBy": "Studio embedding",
                          "requestPath": "/api/query/embeddings", "embeddingType": embedding_type}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown search mode: {body.mode}")
    except OpenArchForbidden:
        raise HTTPException(status_code=403, detail="Not permitted") from None
    except OpenArchUnavailable:
        raise HTTPException(status_code=503, detail="OpenArch is unreachable") from None

    provenance["tookMs"] = round((time.monotonic() - started) * 1000)
    return {"mode": body.mode, "results": results, "provenance": provenance}
