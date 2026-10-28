"""Ragas-backed grading of Studio answers; the only module that imports Ragas."""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable, Mapping

from studio_eval.client import ChatResult
from studio_eval.golden import GoldenEntry

log = logging.getLogger(__name__)

METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
UNANSWERABLE_METRICS = {"faithfulness"}
NEEDS_CONTEXT = {"faithfulness", "context_precision", "context_recall"}

MetricFn = Callable[[dict], Awaitable[float | None]]


def _ragas_metrics(base_url: str, model: str, embed_model: str) -> dict[str, MetricFn]:
    from openai import AsyncOpenAI
    from ragas.embeddings import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    client = AsyncOpenAI(base_url=base_url, api_key="ollama", max_retries=0)
    # reasoning_effort=none keeps qwen3 from emitting <think> blocks that break structured output
    llm = llm_factory(model, client=client, temperature=0, reasoning_effort="none")
    embeddings = embedding_factory("openai", model=embed_model, client=client)

    faithfulness = Faithfulness(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
    precision = ContextPrecisionWithReference(llm=llm)
    recall = ContextRecall(llm=llm)

    async def run_faithfulness(s: dict):
        r = await faithfulness.ascore(s["user_input"], s["response"], s["retrieved_contexts"])
        return r.value

    async def run_relevancy(s: dict):
        return (await relevancy.ascore(s["user_input"], s["response"])).value

    async def run_precision(s: dict):
        r = await precision.ascore(s["user_input"], s["reference"], s["retrieved_contexts"])
        return r.value

    async def run_recall(s: dict):
        r = await recall.ascore(s["user_input"], s["retrieved_contexts"], s["reference"])
        return r.value

    return {
        "faithfulness": run_faithfulness,
        "answer_relevancy": run_relevancy,
        "context_precision": run_precision,
        "context_recall": run_recall,
    }


def _to_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


class Judge:
    def __init__(
        self,
        base_url: str,
        model: str,
        embed_model: str,
        metrics: Mapping[str, MetricFn] | None = None,
    ):
        self._metrics = (
            dict(metrics) if metrics is not None else _ragas_metrics(base_url, model, embed_model)
        )

    async def score(self, entry: GoldenEntry, result: ChatResult) -> dict[str, float | None]:
        scores: dict[str, float | None] = dict.fromkeys(METRIC_NAMES)
        if result.error:
            return scores
        contexts = [c.snippet for c in result.citations if c.snippet.strip()]
        sample = {
            "user_input": entry.question,
            "response": result.answer,
            "retrieved_contexts": contexts,
            "reference": entry.answer,
        }
        for name in METRIC_NAMES:
            if entry.kind == "unanswerable" and name not in UNANSWERABLE_METRICS:
                continue
            if name in NEEDS_CONTEXT and not contexts:
                continue
            try:
                scores[name] = _to_float(await self._metrics[name](sample))
            except Exception as exc:
                log.warning("entry %s: metric %s failed: %s", entry.id, name, exc)
        return scores
