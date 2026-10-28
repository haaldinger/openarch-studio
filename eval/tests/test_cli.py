import asyncio
import json

import pytest

from studio_eval import cli
from studio_eval.client import ChatResult, Citation, StudioError

GOLDEN = """\
- id: fact-one
  question: Total?
  answer: 10 EUR
  evidence: "10"
  sources: [{file: a.tif, page: 1}]
  lang: en
  kind: fact
- id: fact-two
  question: Vendor?
  answer: ACME
  evidence: "ACME"
  sources: [{file: b.tif, page: 2}]
  lang: de
  kind: fact
- id: nope
  question: Moon?
  answer: unknown
  sources: []
  lang: en
  kind: unanswerable
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "a.tif").write_bytes(b"x")
    (samples / "b.tif").write_bytes(b"x")
    golden = tmp_path / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    monkeypatch.setattr(cli, "EVAL_DIR", tmp_path)
    monkeypatch.setenv("STUDIO_EVAL_SAMPLES_DIR", str(samples))
    for var in (
        "STUDIO_EVAL_URL", "STUDIO_EVAL_USER", "STUDIO_EVAL_PASSWORD",
        "STUDIO_EVAL_JUDGE_BASE_URL", "STUDIO_EVAL_JUDGE_MODEL", "STUDIO_EVAL_EMBED_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, golden


EVENTS: list[tuple[str, str]] = []


class FakeClient:
    instances: list = []

    def __init__(self, base_url, user, password):
        self.args = (base_url, user, password)
        self.asked: list[str] = []
        self.fail_on: str | None = None
        self.errors: dict[str, BaseException] = {}
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def login(self):
        pass

    def ensure_folder(self, title):
        assert title == "Eval corpus"
        return "folder-1"

    def ensure_corpus(self, folder_id, samples_dir, timeout_s=900):
        assert folder_id == "folder-1"
        return {"a.tif": "doc-a", "b.tif": "doc-b"}

    def ask(self, question, scope):
        assert scope == "folder-1"
        self.asked.append(question)
        EVENTS.append(("ask", question))
        if question in self.errors:
            raise self.errors[question]
        if question == self.fail_on:
            raise StudioError("Ask is disabled — is Studio in baseline mode?", fatal=True)
        if question == "Total?":
            cites = [Citation("doc-a", "a.tif", 1, "total 10", 0.9, 0.8)]
            return ChatResult("10 EUR", cites, rerank="ok")
        if question == "Vendor?":
            return ChatResult("", [], rerank=None, error="run error")
        return ChatResult("I don't have enough information in the indexed content to answer that.", [])

    def extracted_text(self, doc_id):
        return {2: "second", 1: "first"} if doc_id == "doc-a" else {1: "only"}


class FakeJudge:
    def __init__(self, base_url, model, embed_model):
        self.args = (base_url, model, embed_model)
        self.running = 0
        self.peak = 0

    async def score(self, entry, result):
        EVENTS.append(("grade", entry.id))
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        return {"faithfulness": 0.75, "answer_relevancy": None}


def run(args, **kw):
    FakeClient.instances = []
    EVENTS.clear()
    return cli.main(args, client_factory=FakeClient, judge_factory=FakeJudge, **kw)


def only_result(tmp_path):
    files = list((tmp_path / "results").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def test_run_end_to_end(env, capsys):
    tmp_path, golden = env
    assert run(["run", "--label", "t1", "--golden", str(golden)]) == 0
    path, res = only_result(tmp_path)
    assert path.name.endswith("-t1.json")
    assert res["studio_url"] == "http://localhost:8900"
    assert res["judge_model"] == "qwen3"
    assert res["judge_embed_model"] == "nomic-embed-text"
    assert res["note"] is None and res["partial"] is False
    assert res["rerank_statuses"] == ["ok"]
    assert res["rerank_counts"] == {"none": 1, "ok": 1}
    rows = {r["id"]: r for r in res["rows"]}
    assert list(rows) == ["fact-one", "fact-two", "nope"]
    one = rows["fact-one"]
    assert one["metrics"]["hit"] == 1.0 and one["metrics"]["mrr"] == 1.0
    assert one["metrics"]["false_abstain"] == 0.0
    assert one["metrics"]["faithfulness"] == 0.75
    assert one["metrics"]["evidence_hit"] == 1.0 and one["metrics"]["evidence_mrr"] == 1.0
    assert rows["fact-two"]["metrics"]["evidence_hit"] is None
    assert "evidence_hit" not in rows["nope"]["metrics"] or rows["nope"]["metrics"]["evidence_hit"] is None
    assert one["citations"][0]["title"] == "a.tif"
    assert one["answer"] == "10 EUR" and one["question"] == "Total?" and one["rerank"] == "ok"
    assert rows["fact-two"]["error"] == "run error"
    assert rows["nope"]["metrics"]["abstain_correct"] == 1.0
    out = capsys.readouterr().out
    assert "[ask 1/3] fact-one: ok" in out
    assert "[ask 2/3] fact-two: ERROR run error" in out
    assert "[grade 1/2]" in out and "[grade 2/2]" in out
    assert "fact-one: hit=1.000 mrr=1.000 graded" in out
    assert "rerank: none=1, ok=1" in out
    assert "[overall]" in out and "errors: 1" in out
    assert FakeClient.instances[0].args == ("http://localhost:8900", "admin", "password")


def test_run_reads_env_settings(env, monkeypatch):
    tmp_path, golden = env
    monkeypatch.setenv("STUDIO_EVAL_URL", "http://studio:1")
    monkeypatch.setenv("STUDIO_EVAL_USER", "bob")
    monkeypatch.setenv("STUDIO_EVAL_PASSWORD", "pw")
    monkeypatch.setenv("STUDIO_EVAL_JUDGE_MODEL", "m")
    created = []

    def judge_factory(*a):
        created.append(a)
        return FakeJudge(*a)

    FakeClient.instances = []
    code = cli.main(
        ["run", "--golden", str(golden)], client_factory=FakeClient, judge_factory=judge_factory
    )
    assert code == 0
    assert FakeClient.instances[0].args == ("http://studio:1", "bob", "pw")
    assert created == [("http://localhost:11434/v1", "m", "nomic-embed-text")]


def test_only_filters_entries(env):
    tmp_path, golden = env
    assert run(["run", "--golden", str(golden), "--only", "nope", "fact-one"]) == 0
    assert FakeClient.instances[0].asked == ["Total?", "Moon?"]
    _, res = only_result(tmp_path)
    assert [r["id"] for r in res["rows"]] == ["fact-one", "nope"]


def test_only_unknown_id_exits_2(env, capsys):
    _, golden = env
    assert run(["run", "--golden", str(golden), "--only", "zzz"]) == 2
    assert "zzz" in capsys.readouterr().err


def test_studio_error_exits_2_without_traceback(env, capsys):
    tmp_path, golden = env

    class Failing(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.fail_on = "Total?"

    code = cli.main(["run", "--golden", str(golden)], client_factory=Failing, judge_factory=FakeJudge)
    err = capsys.readouterr().err
    assert code == 2
    assert "baseline mode" in err
    assert "Traceback" not in err
    assert not (tmp_path / "results").exists()  # nothing completed yet


def last_result(tmp_path):
    return only_result(tmp_path)[1]


def test_non_fatal_chat_error_is_recorded_and_run_continues(env, capsys):
    tmp_path, golden = env

    class Flaky(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.errors = {"Total?": StudioError("POST /api/chat failed: HTTP 503")}

    EVENTS.clear()
    code = cli.main(["run", "--golden", str(golden)], client_factory=Flaky, judge_factory=FakeJudge)
    assert code == 0
    res = last_result(tmp_path)
    rows = {r["id"]: r for r in res["rows"]}
    assert res["partial"] is False and list(rows) == ["fact-one", "fact-two", "nope"]
    assert rows["fact-one"]["error"] == "POST /api/chat failed: HTTP 503"
    assert all(v is None for v in rows["fact-one"]["metrics"].values())
    assert rows["nope"]["metrics"]["abstain_correct"] == 1.0
    out = capsys.readouterr().out
    assert "[ask 1/3] fact-one: ERROR POST /api/chat failed: HTTP 503" in out
    assert "errors: 2" in out


@pytest.mark.parametrize("fatal_error", [StudioError("not signed in / sign-in expired", fatal=True)])
def test_fatal_error_mid_run_writes_partial_results(env, capsys, fatal_error):
    tmp_path, golden = env

    class Dies(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.errors = {"Vendor?": fatal_error}

    code = cli.main(["run", "--golden", str(golden), "--label", "p"], client_factory=Dies, judge_factory=FakeJudge)
    captured = capsys.readouterr()
    assert code == 2
    path, res = only_result(tmp_path)
    assert res["partial"] is True
    assert [r["id"] for r in res["rows"]] == ["fact-one"]
    assert "sign-in expired" in captured.err and "Traceback" not in captured.err
    assert str(path) in captured.out + captured.err
    assert "partial" in (captured.out + captured.err).lower()
    assert "PARTIAL" in captured.out


def test_keyboard_interrupt_while_asking_writes_partial_results(env, capsys):
    tmp_path, golden = env

    class Interrupted(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.errors = {"Vendor?": KeyboardInterrupt()}

    code = cli.main(["run", "--golden", str(golden)], client_factory=Interrupted, judge_factory=FakeJudge)
    captured = capsys.readouterr()
    assert code == 130
    res = last_result(tmp_path)
    assert res["partial"] is True and [r["id"] for r in res["rows"]] == ["fact-one"]
    assert "Traceback" not in captured.err
    assert "interrupted" in captured.err.lower()


def test_keyboard_interrupt_while_grading_keeps_asked_rows(env, capsys):
    tmp_path, golden = env

    class Boom(FakeJudge):
        async def score(self, entry, result):
            if entry.id == "nope":
                raise KeyboardInterrupt
            return await super().score(entry, result)

    code = cli.main(
        ["run", "--golden", str(golden), "--concurrency", "1"],
        client_factory=FakeClient, judge_factory=Boom,
    )
    assert code == 130
    res = last_result(tmp_path)
    assert res["partial"] is True
    assert [r["id"] for r in res["rows"]] == ["fact-one", "fact-two", "nope"]
    assert res["rows"][0]["metrics"]["faithfulness"] == 0.75
    assert "faithfulness" not in res["rows"][2]["metrics"]
    assert "Traceback" not in capsys.readouterr().err


def test_keyboard_interrupt_with_no_rows_writes_nothing(env, capsys):
    tmp_path, golden = env

    class Interrupted(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.errors = {"Total?": KeyboardInterrupt()}

    code = cli.main(["run", "--golden", str(golden)], client_factory=Interrupted, judge_factory=FakeJudge)
    assert code == 130
    assert not (tmp_path / "results").exists()


def test_all_questions_are_asked_before_any_grading(env):
    _, golden = env
    assert run(["run", "--golden", str(golden)]) == 0
    kinds = [k for k, _ in EVENTS]
    assert kinds == ["ask", "ask", "ask", "grade", "grade"]


def test_note_is_stored_and_shown(env, capsys):
    tmp_path, golden = env
    note = "studio embed=nomic-embed-text chat=llama3.2:3b"
    assert run(["run", "--golden", str(golden), "--note", note]) == 0
    assert last_result(tmp_path)["note"] == note
    assert f"note: {note}" in capsys.readouterr().out


def test_golden_error_exits_2(env, capsys):
    tmp_path, _ = env
    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: Bad Id\n", encoding="utf-8")
    assert run(["run", "--golden", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "id" in err and "Traceback" not in err
    assert FakeClient.instances == []


def test_evidence_problems_are_warnings(env, capsys):
    tmp_path, golden = env
    fixtures = tmp_path / "fixtures" / "extracted"
    fixtures.mkdir(parents=True)
    (fixtures / "a.tif.md").write_text("nothing", encoding="utf-8")
    assert run(["run", "--golden", str(golden)]) == 0
    err = capsys.readouterr().err
    assert "warning" in err.lower() and "fact-one" in err


def test_concurrency_bounded(env):
    _, golden = env
    judges: list[FakeJudge] = []

    def judge_factory(*a):
        judges.append(FakeJudge(*a))
        return judges[-1]

    cli.main(
        ["run", "--golden", str(golden), "--concurrency", "1"],
        client_factory=FakeClient, judge_factory=judge_factory,
    )
    assert judges[0].peak == 1


def test_fixtures_writes_pages(env, capsys):
    tmp_path, _ = env
    assert run(["fixtures"]) == 0
    out_dir = tmp_path / "fixtures" / "extracted"
    assert (out_dir / "a.tif.md").read_text(encoding="utf-8") == "first\n\n<!-- page 2 -->\n\nsecond"
    assert (out_dir / "b.tif.md").read_text(encoding="utf-8") == "only"
    assert "a.tif.md" in capsys.readouterr().out


def test_compare_command(env, capsys, tmp_path):
    from studio_eval.report import build_result, write_result

    settings = {"studio_url": "u", "judge_model": "j", "embed_model": "e"}
    row = lambda v: [{"id": "a", "kind": "fact", "lang": "en", "metrics": {"hit": v}}]
    pa = write_result(build_result("A", settings, row(0.0), []), tmp_path / "ra")
    pb = write_result(build_result("B", settings, row(1.0), []), tmp_path / "rb")
    assert run(["compare", str(pa), str(pb)]) == 0
    assert "+1.000" in capsys.readouterr().out


def test_compare_missing_file_exits_2(env, capsys):
    assert run(["compare", "/nope/a.json", "/nope/b.json"]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_default_samples_dir_resolves_to_repo_sample_images(monkeypatch):
    monkeypatch.delenv("STUDIO_EVAL_SAMPLES_DIR", raising=False)
    import studio_eval

    expected = (cli.Path(studio_eval.__file__).parent.parent / "../../../sample_images").resolve()
    assert cli.settings_from_env()["samples_dir"] == expected
