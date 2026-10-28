import json

from studio_eval.report import build_result, compare, summary_table, write_result

SETTINGS = {"studio_url": "http://s", "judge_model": "qwen3", "embed_model": "nomic"}


def row(id, kind, lang, **metrics):
    return {
        "id": id, "kind": kind, "lang": lang, "metrics": metrics,
        "question": "q", "answer": "a", "citations": [], "rerank": None, "error": None,
    }


ROWS = [
    row("a", "fact", "en", hit=1.0, mrr=1.0),
    row("b", "fact", "de", hit=0.0, mrr=0.0),
    row("c", "unanswerable", "en", abstain_correct=1.0, hit=None),
]


def test_build_result_shape():
    res = build_result("base", SETTINGS, ROWS, ["ok", None, "ok", "fallback"])
    assert res["label"] == "base"
    assert res["studio_url"] == "http://s"
    assert res["judge_model"] == "qwen3"
    assert res["embed_model"] == "nomic"
    assert res["rerank_statuses"] == ["fallback", "ok"]
    assert res["rows"] == ROWS
    assert res["aggregates"]["overall"]["hit"] == {"mean": 0.5, "n": 2, "skipped": 1}
    assert res["timestamp"].endswith("Z")


def test_write_result_names_file_by_timestamp_and_label(tmp_path):
    res = build_result("my run/1", SETTINGS, ROWS, [])
    res["timestamp"] = "2026-10-27T13:05:09Z"
    path = write_result(res, tmp_path / "results")
    assert path.name == "20261027T130509Z-my-run-1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["label"] == "my run/1"


def test_summary_table_sections_and_error_count():
    rows = ROWS + [{**row("d", "fact", "en"), "error": "boom"}]
    out = summary_table(build_result("base", SETTINGS, rows, []))
    assert "[overall]" in out
    assert "[by_kind: fact]" in out and "[by_kind: unanswerable]" in out
    assert "[by_lang: de]" in out and "[by_lang: en]" in out
    assert "hit" in out and "0.500" in out and "n=2 skipped=2" in out
    assert "errors: 1" in out


def test_compare_deltas_and_one_sided_ids():
    a = build_result("A", SETTINGS, [row("a", "fact", "en", hit=0.5), row("x", "fact", "en", hit=0.5)], [])
    b = build_result("B", SETTINGS, [row("a", "fact", "en", hit=1.0, mrr=1.0), row("y", "fact", "en", hit=1.0)], [])
    out = compare(a, b)
    hit_line = next(l for l in out.splitlines() if l.strip().startswith("hit"))
    assert "0.500" in hit_line and "1.000" in hit_line and "+0.500" in hit_line
    mrr_line = next(l for l in out.splitlines() if l.strip().startswith("mrr"))
    assert "—" in mrr_line
    assert "only in A: x" in out
    assert "only in B: y" in out
    assert "[by_kind: fact]" in out and "[by_lang: en]" in out
