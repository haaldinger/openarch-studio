from collections import Counter
from pathlib import Path

from studio_eval.golden import check_evidence, load_golden

EVAL_DIR = Path(__file__).resolve().parents[1]
SAMPLES = (EVAL_DIR / ".." / ".." / ".." / "sample_images").resolve()
GOLDEN = EVAL_DIR / "golden.yaml"
FIXTURES = EVAL_DIR / "fixtures" / "extracted"


def test_evidence_is_verbatim_in_fixtures():
    entries = load_golden(GOLDEN, SAMPLES)
    assert check_evidence(entries, FIXTURES) == []


def test_golden_set_coverage():
    entries = load_golden(GOLDEN, SAMPLES)
    kinds = Counter(e.kind for e in entries)
    langs = {e.lang for e in entries}
    assert 20 <= len(entries) <= 30
    assert kinds["fact"] >= 12
    assert kinds["cross_doc"] >= 3
    assert kinds["unanswerable"] >= 2
    assert {"de", "fr", "es", "nl"} <= langs
