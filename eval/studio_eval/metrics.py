"""Deterministic retrieval and abstention metrics, plus aggregation."""

from __future__ import annotations

from collections import defaultdict

from .client import ChatResult
from .golden import GoldenEntry

_FIXED_REPLY = "i don't have enough information in the indexed content to answer that."
# Heuristic substring lists: they can over- or under-match.
_ALWAYS_DECLINE = (
    _FIXED_REPLY,
    "don't have enough information",
    "do not have enough information",
    "not enough information",
)
_GUARDED_DECLINE = (
    "cannot find",
    "can't find",
    "no information about",
    "not mentioned in",
    "isn't mentioned in",
    "is not mentioned",
    "does not mention",
    "do not mention",
    "no mention of",
    "does not contain",
    "keine informationen",
    "aucune information",
    "pas d'information",
    "no hay información",
    "no tengo suficiente información",
    "geen informatie",
)
_SHORT_ANSWER_CHARS = 200


def declined(answer: str, has_citations: bool = False) -> bool:
    text = " ".join(answer.replace("\u2019", "'").lower().split())
    if any(p in text for p in _ALWAYS_DECLINE):
        return True
    guarded = len(text) < _SHORT_ANSWER_CHARS and not has_citations
    return guarded and any(p in text for p in _GUARDED_DECLINE)


def retrieval_scores(entry: GoldenEntry, result: ChatResult) -> dict[str, float | None]:
    if entry.kind == "unanswerable" or result.error:
        return {"hit": None, "mrr": None}
    expected = {(s.file, s.page) for s in entry.sources}
    for rank, c in enumerate(result.citations, start=1):
        if (c.title, c.page) in expected:
            return {"hit": 1.0, "mrr": 1 / rank}
    return {"hit": 0.0, "mrr": 0.0}


def abstention_scores(entry: GoldenEntry, result: ChatResult) -> dict[str, float | None]:
    scores: dict[str, float | None] = {"abstain_correct": None, "false_abstain": None}
    if result.error:
        return scores
    key = "abstain_correct" if entry.kind == "unanswerable" else "false_abstain"
    scores[key] = 1.0 if declined(result.answer, has_citations=bool(result.citations)) else 0.0
    return scores


def _summarize(rows: list[dict]) -> dict[str, dict]:
    names = sorted({m for r in rows for m in r["metrics"]})
    out: dict[str, dict] = {}
    for name in names:
        values = [r["metrics"].get(name) for r in rows]
        present = [v for v in values if v is not None]
        out[name] = {
            "mean": sum(present) / len(present) if present else None,
            "n": len(present),
            "skipped": len(values) - len(present),
        }
    return out


def aggregate(rows: list[dict]) -> dict:
    by_kind: dict[str, list[dict]] = defaultdict(list)
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
        by_lang[r["lang"]].append(r)
    return {
        "overall": _summarize(rows),
        "by_kind": {k: _summarize(v) for k, v in by_kind.items()},
        "by_lang": {k: _summarize(v) for k, v in by_lang.items()},
    }
