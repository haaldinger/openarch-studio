import pytest

from studio_eval.client import ChatResult, Citation
from studio_eval.golden import GoldenEntry, Source
from studio_eval.metrics import abstention_scores, aggregate, declined, retrieval_scores

FIXED = "I don't have enough information in the indexed content to answer that."


def cite(title: str, page: int) -> Citation:
    return Citation("d", title, page, "snip", None, None)


def entry(kind: str = "fact", sources: list[Source] | None = None) -> GoldenEntry:
    if sources is None:
        sources = [] if kind == "unanswerable" else [Source("a.pdf", 2)]
    return GoldenEntry("e1", "q", "a", None, sources, "en", kind)


def result(citations: list[Citation] | None = None, answer: str = "An answer.", error: str | None = None):
    return ChatResult(answer=answer, citations=citations or [], error=error)


def test_hit_and_mrr_rank_one():
    s = retrieval_scores(entry(), result([cite("a.pdf", 2), cite("b.pdf", 1)]))
    assert s == {"hit": 1.0, "mrr": 1.0}


def test_mrr_rank_three():
    s = retrieval_scores(entry(), result([cite("x.pdf", 2), cite("a.pdf", 1), cite("a.pdf", 2)]))
    assert s["hit"] == 1.0
    assert s["mrr"] == pytest.approx(1 / 3)


def test_no_match():
    assert retrieval_scores(entry(), result([cite("x.pdf", 2)])) == {"hit": 0.0, "mrr": 0.0}


def test_no_citations():
    assert retrieval_scores(entry(), result()) == {"hit": 0.0, "mrr": 0.0}


def test_title_must_match_exactly():
    s = retrieval_scores(entry(), result([cite("A.pdf", 2), cite("a.pdf ", 2), cite("sub/a.pdf", 2)]))
    assert s == {"hit": 0.0, "mrr": 0.0}


def test_page_must_match():
    assert retrieval_scores(entry(), result([cite("a.pdf", 3)])) == {"hit": 0.0, "mrr": 0.0}


def test_any_expected_source_matches():
    e = entry("cross_doc", [Source("a.pdf", 2), Source("b.pdf", 5)])
    assert retrieval_scores(e, result([cite("b.pdf", 5)])) == {"hit": 1.0, "mrr": 1.0}


def test_retrieval_unanswerable_is_none():
    s = retrieval_scores(entry("unanswerable"), result([cite("a.pdf", 2)]))
    assert s == {"hit": None, "mrr": None}


def test_retrieval_error_is_none():
    s = retrieval_scores(entry(), result([cite("a.pdf", 2)], error="boom"))
    assert s == {"hit": None, "mrr": None}


@pytest.mark.parametrize(
    "answer",
    [
        FIXED,
        FIXED.upper(),
        "Sorry.  " + FIXED.replace(" ", "\n"),
        "I do not have enough information about that.",
        "There is not enough information here.",
        "I cannot find it.",
        "I can't find that.",
        "There is no information about this.",
        "That is not mentioned in the documents.",
        "It isn't mentioned in the text.",
        "It is not mentioned anywhere.",
        "I don\u2019t have enough information to say.",
        "I can\u2019t find that.",
        "It isn\u2019t mentioned in the text.",
    ],
)
def test_declined_true(answer):
    assert declined(answer)


@pytest.mark.parametrize("answer", ["", "The warranty lasts two years [1].", "Information is available on page 3."])
def test_declined_false(answer):
    assert not declined(answer)


CAVEAT = "Total is €120.50 [1]. I cannot find a due date."


def test_partial_answer_with_citations_is_not_declined():
    assert not declined(CAVEAT, has_citations=True)


def test_partial_answer_without_citations_is_declined():
    assert declined(CAVEAT, has_citations=False)


def test_active_voice_refusal_short_is_declined():
    assert declined("The documents do not mention a due date.")


@pytest.mark.parametrize(
    "answer",
    [
        "Keine Informationen dazu.",
        "Aucune information sur ce sujet.",
        "Pas d'information disponible.",
        "No hay información sobre eso.",
        "No tengo suficiente información.",
        "Geen informatie beschikbaar.",
    ],
)
def test_non_english_refusal_short_is_declined(answer):
    assert declined(answer)


def test_long_answer_with_citations_mentioning_no_mention_of_is_not_declined():
    answer = (
        "The policy covers water damage in detail across several sections [1][2]. "
        "Coverage for flood events is described on page four, while there is no mention of "
        "earthquake damage in the excerpt provided, so that case is not addressed by this document "
        "and additional sources would be needed to answer it fully."
    )
    assert len(answer) >= 200
    assert not declined(answer, has_citations=True)


def test_abstention_unanswerable():
    assert abstention_scores(entry("unanswerable"), result(answer=FIXED)) == {
        "abstain_correct": 1.0,
        "false_abstain": None,
    }
    assert abstention_scores(entry("unanswerable"), result(answer="It is 42.")) == {
        "abstain_correct": 0.0,
        "false_abstain": None,
    }


def test_abstention_answerable():
    assert abstention_scores(entry(), result(answer=FIXED)) == {"abstain_correct": None, "false_abstain": 1.0}
    assert abstention_scores(entry(), result(answer="Two years.")) == {
        "abstain_correct": None,
        "false_abstain": 0.0,
    }


def test_abstention_error_is_none():
    for kind in ("fact", "unanswerable"):
        s = abstention_scores(entry(kind), result(answer=FIXED, error="boom"))
        assert s == {"abstain_correct": None, "false_abstain": None}


def row(id: str, kind: str, lang: str, **metrics: float | None) -> dict:
    return {"id": id, "kind": kind, "lang": lang, "metrics": metrics}


def test_aggregate_overall_skips_none():
    rows = [
        row("a", "fact", "en", hit=1.0, mrr=1.0),
        row("b", "fact", "en", hit=0.0, mrr=0.0),
        row("c", "unanswerable", "de", hit=None, mrr=None),
    ]
    out = aggregate(rows)
    assert out["overall"]["hit"] == {"mean": 0.5, "n": 2, "skipped": 1}
    assert out["overall"]["mrr"] == {"mean": 0.5, "n": 2, "skipped": 1}


def test_aggregate_all_null_mean_none():
    out = aggregate([row("a", "fact", "en", faithfulness=None)])
    assert out["overall"]["faithfulness"] == {"mean": None, "n": 0, "skipped": 1}


def test_aggregate_groups():
    rows = [
        row("a", "fact", "en", hit=1.0),
        row("b", "fact", "de", hit=0.0),
        row("c", "cross_doc", "en", hit=1.0),
    ]
    out = aggregate(rows)
    assert out["by_kind"]["fact"]["hit"] == {"mean": 0.5, "n": 2, "skipped": 0}
    assert out["by_kind"]["cross_doc"]["hit"] == {"mean": 1.0, "n": 1, "skipped": 0}
    assert out["by_lang"]["en"]["hit"] == {"mean": 1.0, "n": 2, "skipped": 0}
    assert out["by_lang"]["de"]["hit"] == {"mean": 0.0, "n": 1, "skipped": 0}


def test_aggregate_metric_union_and_missing_counts_as_skipped():
    rows = [row("a", "fact", "en", hit=1.0), row("b", "fact", "en", faithfulness=0.5)]
    out = aggregate(rows)
    assert out["overall"]["hit"] == {"mean": 1.0, "n": 1, "skipped": 1}
    assert out["overall"]["faithfulness"] == {"mean": 0.5, "n": 1, "skipped": 1}


def test_aggregate_empty():
    assert aggregate([]) == {"overall": {}, "by_kind": {}, "by_lang": {}}
