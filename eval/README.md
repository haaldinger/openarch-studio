# Studio evaluation harness

Asks a running Studio a fixed set of questions over the sample documents and scores what comes back,
so a change to extraction, chunking, embedding, reranking or the chat model can be compared with an
earlier run.

## Setup

```bash
cd eval
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
```

Prerequisites:

- The Studio stack is running (`docker compose up -d --build` from the project root) and reachable
  at `STUDIO_EVAL_URL`.
- Ollama runs on the host (not only inside Compose) with the grader and embedding models pulled:
  `ollama pull qwen3` and `ollama pull nomic-embed-text`. Ragas calls it at
  `STUDIO_EVAL_JUDGE_BASE_URL`.
- The sample documents are in `sample_images/` at the OpenArch repo root (override with
  `STUDIO_EVAL_SAMPLES_DIR`).

## Usage

```bash
.venv/bin/studio-eval run --label my-change      # ask, grade, write eval/results/<UTC>-<label>.json
.venv/bin/studio-eval run --only <id> <id>       # re-run selected golden ids
.venv/bin/studio-eval run --concurrency 1        # concurrent judge gradings (default 2)
.venv/bin/studio-eval run --golden other.yaml    # use another golden set
.venv/bin/studio-eval compare A.json B.json      # per-metric means and deltas
.venv/bin/studio-eval fixtures                   # save Studio's extracted text to eval/fixtures/extracted
```

`run` signs in, finds or creates the `Eval corpus` folder, uploads only the sample files not already
in it, waits for enrichment (up to 15 minutes), then asks every question scoped to that folder and
grades the answers. `fixtures` is for refreshing the extracted text that the tests use to verify the
golden evidence.

Results in `eval/results/` are git-ignored. Committed reference runs go in `eval/baselines/`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `STUDIO_EVAL_URL` | `http://localhost:8900` | Studio base URL. |
| `STUDIO_EVAL_USER` | `admin` | OpenArch user the harness signs in as. |
| `STUDIO_EVAL_PASSWORD` | `password` | That user's password. |
| `STUDIO_EVAL_JUDGE_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint serving the grader and embedding models. |
| `STUDIO_EVAL_JUDGE_MODEL` | `qwen3` | Grader model for the Ragas metrics. |
| `STUDIO_EVAL_EMBED_MODEL` | `nomic-embed-text` | Embedding model for `answer_relevancy`. |
| `STUDIO_EVAL_SAMPLES_DIR` | `../../../sample_images` (relative to `eval/`) | Sample documents uploaded to the corpus. |

## Golden set

`golden.yaml` holds 28 entries: 20 `fact` (one document), 5 `cross_doc` (several documents) and 3
`unanswerable` (nothing in the corpus answers them). Four of the entries are questions in German,
French, Spanish and Dutch; the rest are English. Each answerable entry has a reference answer and the
file and page it comes from. The tests check that evidence against `fixtures/extracted`.

## Metrics

Deterministic, computed from the citations and answer text:

| Metric | Meaning |
|---|---|
| `hit` | 1 if any citation is an expected source (same file and page), else 0. Not scored for `unanswerable`. |
| `mrr` | 1 / rank of the first expected citation, 0 if none. Not scored for `unanswerable`. |
| `abstain_correct` | For `unanswerable` entries: 1 if Studio declined. |
| `false_abstain` | For answerable entries: 1 if Studio declined anyway (lower is better). |

A decline is Studio's fixed reply, or one of a few "not enough information" phrases anywhere in the
answer. Some looser phrases ("cannot find", "no mention of", and their German, French, Spanish and
Dutch forms) count only for answers under 200 characters without citations. This is a heuristic and
can over- or under-match.

Graded by Ragas with the local grader (thinking disabled):

| Metric | Meaning |
|---|---|
| `faithfulness` | Share of the answer's claims supported by the cited snippets. Also scored for `unanswerable`. |
| `answer_relevancy` | How well the answer addresses the question. |
| `context_precision` | Whether the cited snippets that matter to the reference answer are ranked first. |
| `context_recall` | How much of the reference answer is covered by the cited snippets. |

Context metrics are skipped when an answer has no citations; `unanswerable` entries get only
`faithfulness`. A grader failure records `null` for that metric. Averages ignore nulls and report
`n` (scored) and `skipped` per metric, grouped overall, by `kind` and by `lang`.

## Caveats

- A local 4–8B grader is noisy. Compare runs rather than reading single scores, and expect a few
  skipped metrics.
- A full run takes tens of minutes, mostly grading. Grading on the same machine can slow Studio's
  Ask while it runs, so keep other load off the host.
- If a run aborts, no result file is written. Re-run the entries that did not finish with `--only`.
- Citations are Studio's top chunks after reranking, so `hit` and `mrr` measure what the user sees,
  not raw retrieval. The `rerank_statuses` field in the result records whether reranking ran.
- Ragas is pinned to `0.4.3` with matching `langchain` pins in `pyproject.toml`; upgrade them
  together.
