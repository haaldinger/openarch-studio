# Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local `studio-eval` CLI that runs a golden question set through Studio's Ask and reports deterministic retrieval/abstention metrics plus Ragas-graded scores, with run-to-run comparison.

**Architecture:** A separate Python project in `eval/` that talks to Studio only over its public HTTP API (`/api/session`, `/api/folders`, `/api/documents`, `/api/jobs`, `/api/chat` SSE). Ragas is isolated behind `judge.py`. No change to `api/` or `web/`.

**Tech Stack:** Python 3.12+, httpx, pyyaml, ragas (+ openai client) against host Ollama; pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-27-eval-harness-design.md`

All paths are relative to `pocs/openarch-studio/`. Eval tests: `cd eval && .venv/bin/pytest -q`.

## Global Constraints

- Nothing under `api/` or `web/` changes.
- Defaults: `STUDIO_EVAL_URL=http://localhost:8900`, `STUDIO_EVAL_USER=admin`, `STUDIO_EVAL_PASSWORD=password`, `STUDIO_EVAL_JUDGE_BASE_URL=http://localhost:11434/v1`, `STUDIO_EVAL_JUDGE_MODEL=qwen3`, `STUDIO_EVAL_EMBED_MODEL=nomic-embed-text`, `STUDIO_EVAL_SAMPLES_DIR=../../sample_images` (relative to `eval/`).
- Corpus folder title: `Eval corpus` (root level). Enrichment wait bound: 15 minutes.
- Golden `kind` ∈ {`fact`, `cross_doc`, `unanswerable`}; `lang` ∈ {`en`, `de`, `fr`, `es`, `nl`}; id `[a-z0-9-]+`; `evidence` required for `fact`.
- Decline phrase: `I don't have enough information in the indexed content to answer that.` plus equivalents.
- Ragas is imported only in `studio_eval/judge.py`. Grader failures record `null`, never 0.
- `eval/results/` git-ignored; `eval/baselines/baseline-nomic.json` committed.
- Every new third-party component (Ragas, `qwen3`) in `NOTICE` + README table with a license verified upstream.

## Review Focus

1. Studio returns 403 on `/api/chat` (baseline mode) or 401 (bad credentials) → run stops with a clear message, no traceback (Task 2).
2. An enrichment job fails or never completes for an uploaded sample → run aborts naming the file and stage / timeout (Task 2).
3. Re-running against a stack where the corpus already exists → no duplicate uploads (Task 2).
4. The grader returns unparseable output or the judge endpoint is down → that metric is `null` with the count of skipped entries in aggregates; the run still finishes (Tasks 4, 5).
5. Citation titles that differ in case/path from golden file names (e.g. title set to the file name exactly) → matching compares exact file name to `title`; a mismatch is a miss, not an error (Task 3).

---

### Task 1: Project scaffold and golden set loader

**Files:**
- Create: `eval/pyproject.toml`, `eval/studio_eval/__init__.py`, `eval/studio_eval/golden.py`, `eval/tests/test_golden.py`, `eval/.gitignore` (`results/`, `.venv/`)
- Modify: root `.gitignore` only if needed for `eval/.venv`

**Interfaces:**
- Produces: `@dataclass Source(file: str, page: int)`; `@dataclass GoldenEntry(id, question, answer, evidence: str | None, sources: list[Source], lang, kind)`; `def load_golden(path: Path, samples_dir: Path) -> list[GoldenEntry]` raising `GoldenError(message)` naming the entry id; `def check_evidence(entries, fixtures_dir: Path) -> list[str]` returning problems (empty = ok).
- `pyproject.toml`: package `studio_eval`, console script `studio-eval = "studio_eval.cli:main"`, deps `httpx`, `pyyaml`, `ragas`, `openai`; dev deps `pytest`, `respx`. Pin ragas to the latest release that provides `ragas.llms.llm_factory` (check `pip index versions ragas`).

- [ ] **Step 1:** Create `.venv` (`python3 -m venv .venv && .venv/bin/pip install -e '.[test]'`).
- [ ] **Step 2: Failing tests** — valid file loads; duplicate id; bad kind; bad lang; bad id chars; `fact` without evidence; non-unanswerable without sources; source file missing from samples dir; `check_evidence` reports an evidence string absent from `fixtures/extracted/<file>.md` and passes when present.
- [ ] **Step 3: Implement**; run → PASS.
- [ ] **Step 4: Commit** `feat(eval): scaffold and golden set loader`.

### Task 2: Studio client

**Files:**
- Create: `eval/studio_eval/client.py`, `eval/tests/test_client.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - `class StudioError(Exception)`
  - `@dataclass Citation(doc_id, title, page: int, snippet, score: float | None, vector_score: float | None)`
  - `@dataclass ChatResult(answer: str, citations: list[Citation], rerank: str | None, error: str | None)`
  - `def parse_chat_stream(lines: Iterable[str]) -> ChatResult`
  - `class StudioClient(base_url, user, password)` with `login()`, `ensure_folder(title) -> str`, `ensure_corpus(folder_id, samples_dir, timeout_s=900) -> dict[str, str]` (file name → doc id), `ask(question, scope) -> ChatResult`, `extracted_text(doc_id) -> dict[int, str]` (page → joined chunk text, from `GET /api/documents/{id}/embeddings`).

- [ ] **Step 1:** Read `api/app/routes.py`, `api/app/library.py`, `api/app/jobs.py`, `api/app/chat.py` for exact request/response shapes (session body, folder create, multipart upload field, `_studioJobId`, jobs list shape, embeddings response, SSE `data:` lines and event `type` names). Use the real names in code and tests.
- [ ] **Step 2: Failing tests (respx)** — `parse_chat_stream`: deltas concatenated, citations parsed in order incl. `vectorScore`, `rerank` from `TOOL_CALL_END.result.rerank`, `RUN_ERROR` → `error` set; `login` 401 → `StudioError("sign-in failed …")`; `ask` 403 → `StudioError` mentioning baseline mode; `ensure_folder` reuses an existing folder by title; `ensure_corpus` uploads only missing files, waits until their jobs complete, raises `StudioError` naming file + failed stage, and raises on timeout (inject a short timeout and a fake clock/sleep).
- [ ] **Step 3: Implement**; run → PASS.
- [ ] **Step 4: Commit** `feat(eval): Studio client and chat stream parser`.

### Task 3: Metrics and aggregates

**Files:**
- Create: `eval/studio_eval/metrics.py`, `eval/tests/test_metrics.py`

**Interfaces:**
- Consumes: `GoldenEntry`, `ChatResult`, `Citation`.
- Produces: `def declined(answer: str) -> bool`; `def retrieval_scores(entry, result) -> dict[str, float | None]` (`hit`, `mrr`; both `None` for unanswerable); `def abstention_scores(entry, result) -> dict[str, float | None]` (`abstain_correct` for unanswerable, `false_abstain` for answerable); `def aggregate(rows: list[dict]) -> dict` → `{"overall": {metric: {"mean", "n", "skipped"}}, "by_kind": {...}, "by_lang": {...}}` with nulls skipped and counted.

- [ ] **Step 1: Failing tests** — hit/mrr with match at rank 1, rank 3, none; title must equal file name exactly; page must match; unanswerable → None; `declined` true for the fixed reply and equivalents (case-insensitive), false for a normal answer; aggregates skip None and report `skipped`; by_kind / by_lang grouping.
- [ ] **Step 2: Implement**; run → PASS.
- [ ] **Step 3: Commit** `feat(eval): retrieval and abstention metrics`.

### Task 4: Ragas judge adapter

**Files:**
- Create: `eval/studio_eval/judge.py`, `eval/tests/test_judge.py`

**Interfaces:**
- Produces: `class Judge(base_url, model, embed_model)` with `async def score(entry: GoldenEntry, result: ChatResult) -> dict[str, float | None]` returning `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall` (only `faithfulness` for unanswerable; contexts = citation snippets; reference = `entry.answer`); each metric computed independently, any exception → `None` for that metric (logged). Constructor accepts an injectable `metrics` mapping for tests.

- [ ] **Step 1:** Check the installed Ragas API (`llm_factory`, `embedding_factory`, metric classes and their scoring call) and use it against an OpenAI client with `base_url` = judge URL and a dummy api key.
- [ ] **Step 2: Failing tests** with fake metric objects — all four returned for answerable; only faithfulness for unanswerable; one metric raising → that metric `None`, others present; no citations → context metrics `None`.
- [ ] **Step 3: Implement**; run → PASS.
- [ ] **Step 4: Live smoke** (host Ollama with `qwen3` and `nomic-embed-text`): score one hand-made entry; record the four numbers in the report.
- [ ] **Step 5: Commit** `feat(eval): Ragas judge adapter`.

### Task 5: Report and CLI

**Files:**
- Create: `eval/studio_eval/report.py`, `eval/studio_eval/cli.py`, `eval/tests/test_report.py`, `eval/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `def build_result(label, settings, rows, rerank_seen) -> dict`; `def write_result(result, results_dir) -> Path` (`<UTC %Y%m%dT%H%M%SZ>-<label>.json`); `def summary_table(result) -> str`; `def compare(a: dict, b: dict) -> str` (aggregates side by side with delta; ids only in one file listed). CLI: `studio-eval run [--label L] [--golden PATH] [--only ID ...]`, `studio-eval compare A B`, `studio-eval fixtures` (writes `fixtures/extracted/<file>.md` from the corpus, pages separated by `\n\n<!-- page N -->\n\n`). Settings from the env vars in Global Constraints.

- [ ] **Step 1: Failing tests** — result JSON shape (label, timestamp, Studio URL, judge model, embed model, rerank statuses, rows, aggregates); file naming; summary table includes overall + by_kind + by_lang; compare deltas and one-sided ids; `run` wiring with fake client + fake judge end-to-end (no network) incl. a StudioError → exit code 2 with the message and no traceback.
- [ ] **Step 2: Implement**; run → PASS.
- [ ] **Step 3: Commit** `feat(eval): report, compare, and CLI`.

### Task 6: Golden set

**Files:**
- Create: `eval/fixtures/extracted/*.md`, `eval/golden.yaml`, `eval/tests/test_golden_set.py`

- [ ] **Step 1:** Against the running stack, `studio-eval fixtures` (uploads the corpus into `Eval corpus` if needed, waits for enrichment, writes the 10 fixture files).
- [ ] **Step 2:** Write `golden.yaml`: ~15 `fact`, ~5 `cross_doc`, ~4 non-English questions (de, fr, es, nl), ~3 `unanswerable`; 20–30 total. Every `fact` `evidence` copied verbatim from its fixture; `answer` a short reference sentence containing that value. Cross-doc answers derived only from fixture values.
- [ ] **Step 3: Test** `test_golden_set.py`: `load_golden` passes on the real file and `check_evidence` returns no problems.
- [ ] **Step 4: Commit** `feat(eval): golden set and extracted-text fixtures`.

### Task 7: Baseline run, docs, licenses

**Files:**
- Create: `eval/README.md`, `eval/baselines/baseline-nomic.json`
- Modify: `README.md`, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `NOTICE`, `.env.example`, `AGENTS.md`

- [ ] **Step 1:** `studio-eval run --label baseline-nomic` on the live stack; copy the result to `eval/baselines/baseline-nomic.json`; paste the summary table into the report.
- [ ] **Step 2: Verify licenses** for Ragas (GitHub LICENSE at the pinned version) and `qwen3` (model card) and add both to NOTICE + README table.
- [ ] **Step 3: Docs.** `eval/README.md` (setup, run, compare, fixtures, env vars); root README "Evaluation" section with the baseline summary; deep dive section on method/metrics/caveats (local grader); GLOSSARY *Golden set*, *Eval run*; `.env.example` commented eval vars; AGENTS.md mentions `eval/`.
- [ ] **Step 4: Commit** `docs: evaluation harness and baseline`.
