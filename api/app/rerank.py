"""Cross-encoder reranker client (Hugging Face text-embeddings-inference /rerank).

Never raises: any failure returns the input order with a "skipped (...)" status.
"""

from __future__ import annotations

import logging
import math
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


def _parse_ranking(ranked: object, count: int) -> tuple[list[int], dict[int, float]] | None:
    # Accepts only one entry per input index, with real ints and finite real scores.
    if not isinstance(ranked, list) or len(ranked) != count:
        return None
    by_index: dict[int, float] = {}
    for item in ranked:
        if not isinstance(item, dict):
            return None
        index, score = item.get("index"), item.get("score")
        if type(index) is not int or not 0 <= index < count or index in by_index:
            return None
        if type(score) not in (int, float):
            return None
        try:
            value = float(score)
        except OverflowError:
            return None
        if not math.isfinite(value):
            return None
        by_index[index] = value
    return list(by_index), by_index


class Reranker:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def rerank(self, query: str, texts: list[str]) -> RerankOutcome:
        if not texts:
            return RerankOutcome([], [], "reranked")
        url = self._settings.reranker_url.rstrip("/")
        if not url:
            return self._skip(len(texts), "not configured")

        payload = {"query": query, "texts": [t[:MAX_TEXT_CHARS] for t in texts]}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(f"{url}/rerank", json=payload)
            response.raise_for_status()
            ranked = response.json()
        except httpx.TimeoutException:
            return self._skip(len(texts), "timeout")
        except httpx.HTTPStatusError as exc:
            return self._skip(len(texts), f"HTTP {exc.response.status_code}")
        except (httpx.HTTPError, httpx.InvalidURL):
            return self._skip(len(texts), "unreachable")
        except ValueError:
            return self._skip(len(texts), "incomplete response")

        parsed = _parse_ranking(ranked, len(texts))
        if parsed is None:
            return self._skip(len(texts), "incomplete response")
        order, by_index = parsed
        return RerankOutcome(order, [by_index[i] for i in range(len(texts))], "reranked")

    @staticmethod
    def _skip(count: int, reason: str) -> RerankOutcome:
        log.warning("rerank skipped: %s", reason)
        return RerankOutcome(list(range(count)), [None] * count, f"skipped ({reason})")
