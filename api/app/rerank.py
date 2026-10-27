"""Cross-encoder reranker client (Hugging Face text-embeddings-inference /rerank).

Never raises: any failure returns the input order with a "skipped (...)" status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0
MAX_TEXT_CHARS = 512


@dataclass
class RerankOutcome:
    order: list[int]  # input indexes, best first
    scores: list[float | None]  # aligned to input index
    status: str  # "reranked" or "skipped (<reason>)"


class Reranker:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def rerank(self, query: str, texts: list[str]) -> RerankOutcome:
        if not texts:
            return RerankOutcome([], [], "reranked")
        if not self._settings.reranker_url:
            return self._skip(len(texts), "not configured")

        payload = {"query": query, "texts": [t[:MAX_TEXT_CHARS] for t in texts]}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self._settings.reranker_url}/rerank", json=payload)
            response.raise_for_status()
            ranked = response.json()
        except httpx.TimeoutException:
            return self._skip(len(texts), "timeout")
        except httpx.HTTPStatusError as exc:
            return self._skip(len(texts), f"HTTP {exc.response.status_code}")
        except httpx.TransportError:
            return self._skip(len(texts), "unreachable")
        except ValueError:
            return self._skip(len(texts), "incomplete response")

        try:
            order = [int(item["index"]) for item in ranked]
            by_index = {int(item["index"]): float(item["score"]) for item in ranked}
        except (KeyError, TypeError, ValueError):
            return self._skip(len(texts), "incomplete response")
        if sorted(order) != list(range(len(texts))):
            return self._skip(len(texts), "incomplete response")

        return RerankOutcome(order, [by_index[i] for i in range(len(texts))], "reranked")

    @staticmethod
    def _skip(count: int, reason: str) -> RerankOutcome:
        log.warning("rerank skipped: %s", reason)
        return RerankOutcome(list(range(count)), [None] * count, f"skipped ({reason})")
