from pathlib import Path

import pytest
import yaml

from studio_eval.golden import GoldenEntry, GoldenError, Source, check_evidence, load_golden


def entry(**over):
    base = {
        "id": "pl-total",
        "question": "What is the total?",
        "answer": "100 PLN",
        "evidence": "Total 100",
        "sources": [{"file": "a.tif", "page": 1}],
        "lang": "en",
        "kind": "fact",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not _DROP}


_DROP = object()


@pytest.fixture
def samples(tmp_path: Path) -> Path:
    d = tmp_path / "samples"
    d.mkdir()
    (d / "a.tif").write_bytes(b"x")
    (d / "b.tif").write_bytes(b"x")
    return d


def write(tmp_path: Path, entries) -> Path:
    p = tmp_path / "golden.yaml"
    p.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return p


def test_valid_file_loads(tmp_path, samples):
    p = write(
        tmp_path,
        [
            entry(),
            entry(id="cross", kind="cross_doc", evidence=_DROP, lang="de",
                  sources=[{"file": "a.tif", "page": 1}, {"file": "b.tif", "page": 2}]),
            entry(id="nope", kind="unanswerable", evidence=_DROP, sources=[]),
        ],
    )
    got = load_golden(p, samples)
    assert [e.id for e in got] == ["pl-total", "cross", "nope"]
    assert got[0] == GoldenEntry(
        id="pl-total", question="What is the total?", answer="100 PLN", evidence="Total 100",
        sources=[Source("a.tif", 1)], lang="en", kind="fact",
    )
    assert got[1].evidence is None
    assert got[2].sources == []


def test_duplicate_id(tmp_path, samples):
    with pytest.raises(GoldenError, match="pl-total.*duplicate"):
        load_golden(write(tmp_path, [entry(), entry()]), samples)


@pytest.mark.parametrize("over,needle", [
    ({"kind": "opinion"}, "kind"),
    ({"lang": "xx"}, "lang"),
    ({"id": "Bad_ID"}, "Bad_ID"),
    ({"evidence": _DROP}, "evidence"),
    ({"sources": []}, "sources"),
    ({"sources": [{"file": "a.tif", "page": 0}]}, "page"),
    ({"sources": [{"file": "missing.tif", "page": 1}]}, "missing.tif"),
])
def test_invalid_entry(tmp_path, samples, over, needle):
    with pytest.raises(GoldenError, match=needle):
        load_golden(write(tmp_path, [entry(**over)]), samples)


def test_error_names_entry_id(tmp_path, samples):
    with pytest.raises(GoldenError, match="pl-total"):
        load_golden(write(tmp_path, [entry(kind="opinion")]), samples)


def test_error_uses_index_when_id_missing(tmp_path, samples):
    with pytest.raises(GoldenError, match="#0"):
        load_golden(write(tmp_path, [entry(id=_DROP)]), samples)


def test_unanswerable_must_have_no_sources(tmp_path, samples):
    with pytest.raises(GoldenError, match="sources"):
        load_golden(write(tmp_path, [entry(kind="unanswerable", evidence=_DROP)]), samples)


def test_check_evidence(tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "a.tif.md").write_text("Invoice\nTotal 100 PLN\n", encoding="utf-8")
    ok = GoldenEntry("ok", "q", "a", "Total 100", [Source("a.tif", 1)], "en", "fact")
    bad = GoldenEntry("bad", "q", "a", "Total 999", [Source("a.tif", 1)], "en", "fact")
    nofile = GoldenEntry("nofile", "q", "a", "x", [Source("b.tif", 1)], "en", "fact")
    other = GoldenEntry("un", "q", "a", None, [], "en", "unanswerable")

    assert check_evidence([ok, other], fx) == []
    problems = check_evidence([ok, bad, nofile, other], fx)
    assert len(problems) == 2
    assert "bad" in problems[0] and "Total 999" in problems[0]
    assert "nofile" in problems[1] and "b.tif.md" in problems[1]
