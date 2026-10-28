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
    assert res["judge_embed_model"] == "nomic"
    assert "embed_model" not in res
    assert res["note"] is None and res["partial"] is False
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


def test_build_result_note_partial_and_rerank_counts():
    rows = [
        {**row("a", "fact", "en"), "rerank": "ranked"},
        {**row("b", "fact", "en"), "rerank": "ranked"},
        {**row("c", "fact", "en"), "rerank": "skipped (timeout)"},
        {**row("d", "fact", "en"), "rerank": None},
        {**row("e", "fact", "en"), "rerank": None, "error": "boom"},
    ]
    res = build_result("x", SETTINGS, rows, [], note="studio embed=nomic", partial=True)
    assert res["note"] == "studio embed=nomic" and res["partial"] is True
    assert res["rerank_counts"] == {"ranked": 2, "skipped (timeout)": 1, "none": 1}


def test_summary_table_shows_note_partial_and_rerank_counts():
    rows = [{**row("a", "fact", "en", hit=1.0), "rerank": "ranked"}]
    out = summary_table(build_result("x", SETTINGS, rows, [], note="chat=llama", partial=True))
    assert "note: chat=llama" in out
    assert "PARTIAL" in out
    assert "rerank: ranked=1" in out
    plain = summary_table(build_result("x", SETTINGS, rows, []))
    assert "note:" not in plain and "PARTIAL" not in plain


def test_compare_shows_n_errors_and_rerank_counts():
    a_rows = [
        {**row("a", "fact", "en", hit=1.0), "rerank": "ranked"},
        {**row("b", "fact", "en", hit=0.0), "rerank": "skipped (timeout)"},
        {**row("c", "fact", "en"), "rerank": None, "error": "boom"},
    ]
    b_rows = [{**row("a", "fact", "en", hit=1.0), "rerank": "ranked"}]
    out = compare(build_result("A", SETTINGS, a_rows, []), build_result("B", SETTINGS, b_rows, []))
    hit_line = next(l for l in out.splitlines() if l.strip().startswith("hit"))
    assert "(n=2)" in hit_line and "(n=1)" in hit_line
    assert "errors: 1  rerank: ranked=1, skipped (timeout)=1" in out
    assert "errors: 0  rerank: ranked=1" in out
    assert out.index("errors: 1") < out.index("errors: 0")


def test_compare_reads_old_files_with_embed_model_and_no_counts():
    old = {
        "label": "old", "timestamp": "2026-10-27T00:00:00Z", "studio_url": "u",
        "judge_model": "j", "embed_model": "nomic", "rerank_statuses": [],
        "rows": [row("a", "fact", "en", hit=1.0)],
        "aggregates": {"overall": {"hit": {"mean": 1.0, "n": 1, "skipped": 0}}, "by_kind": {}, "by_lang": {}},
    }
    new = build_result("new", SETTINGS, [row("a", "fact", "en", hit=0.0)], [], note="n1")
    out = compare(old, new)
    assert "judge embed: nomic" in out
    assert "note: n1" in out
