import logging

from studio_eval.client import ChatResult, Citation
from studio_eval.golden import GoldenEntry, Source
from studio_eval.judge import Judge

NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


def entry(kind: str = "fact") -> GoldenEntry:
    sources = [] if kind == "unanswerable" else [Source("a.pdf", 1)]
    return GoldenEntry("e1", "What is the total?", "EUR 10", None, sources, "en", kind)


def result(snippets: list[str] | None = None, error: str | None = None) -> ChatResult:
    cites = [Citation("d", "a.pdf", 1, s, None, None) for s in snippets or []]
    return ChatResult(answer="It is EUR 10.", citations=cites, error=error)


def fakes(calls: list | None = None, **overrides):
    def make(name: str, value):
        async def metric(sample: dict):
            if calls is not None:
                calls.append((name, sample))
            if isinstance(value, Exception):
                raise value
            return value

        return metric

    return {n: make(n, overrides.get(n, 0.5)) for n in NAMES}


def judge(**overrides) -> Judge:
    return Judge("http://x/v1", "m", "e", metrics=fakes(**overrides))


async def test_answerable_returns_all_four():
    calls: list = []
    j = Judge("http://x/v1", "m", "e", metrics=fakes(calls))
    scores = await j.score(entry(), result(["Total EUR 10", "Other"]))
    assert scores == dict.fromkeys(NAMES, 0.5)
    sample = calls[0][1]
    assert sample == {
        "user_input": "What is the total?",
        "response": "It is EUR 10.",
        "retrieved_contexts": ["Total EUR 10", "Other"],
        "reference": "EUR 10",
    }


async def test_unanswerable_only_faithfulness():
    scores = await judge().score(entry("unanswerable"), result(["ctx"]))
    assert scores == {
        "faithfulness": 0.5,
        "answer_relevancy": None,
        "context_precision": None,
        "context_recall": None,
    }


async def test_one_metric_raising_is_none_others_present(caplog):
    j = judge(context_recall=RuntimeError("boom"))
    with caplog.at_level(logging.WARNING):
        scores = await j.score(entry(), result(["ctx"]))
    assert scores["context_recall"] is None
    assert scores["faithfulness"] == 0.5
    assert scores["answer_relevancy"] == 0.5
    assert scores["context_precision"] == 0.5
    assert "e1" in caplog.text and "context_recall" in caplog.text


async def test_no_citations_nulls_context_metrics():
    scores = await judge().score(entry(), result([]))
    assert scores["faithfulness"] is None
    assert scores["context_precision"] is None
    assert scores["context_recall"] is None
    assert scores["answer_relevancy"] == 0.5


async def test_blank_snippets_are_not_contexts():
    calls: list = []
    j = Judge("http://x/v1", "m", "e", metrics=fakes(calls))
    await j.score(entry(), result(["  ", "real"]))
    assert calls[0][1]["retrieved_contexts"] == ["real"]


async def test_error_result_all_none():
    scores = await judge().score(entry(), result(["ctx"], error="boom"))
    assert scores == dict.fromkeys(NAMES, None)


async def test_nan_and_non_numeric_become_none():
    j = judge(faithfulness=float("nan"), context_precision="0.25", answer_relevancy=None)
    scores = await j.score(entry(), result(["ctx"]))
    assert scores["faithfulness"] is None
    assert scores["context_precision"] == 0.25
    assert scores["answer_relevancy"] is None
