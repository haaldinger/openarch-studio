# Evaluation harness (Ragas + retrieval metrics) — design

Date: 2026-10-27 · Status: draft for review · Sub-project 1 of 3 (then multilingual embeddings, then hybrid search)

## Goal

A repeatable, local measurement of Ask quality over the sample invoices, so later changes (embedding model,
hybrid search) can be compared run against run with numbers instead of impressions.

## Invariants

- Nothing in `studio-api` or `studio-web` changes; the harness is a separate client of Studio's public API.
- Runs as a configured Studio user through `/api/chat`, so permissions, reranking and retrieve-then-verify
  are exercised exactly as a user experiences them.
- The only writes are the "Eval corpus" folder and its uploads in OpenArch, made as that user.
- No data leaves the machine by default (grader is local `qwen3`).

## Layout

```text
eval/
├── pyproject.toml        # ragas, httpx, pyyaml; console script `studio-eval`
├── README.md
├── golden.yaml           # the golden set
├── fixtures/extracted/   # saved Docling text per sample (for the golden-answer check)
├── baselines/            # committed baseline result(s)
├── results/              # run outputs (git-ignored)
├── studio_eval/
│   ├── cli.py            # `run`, `compare`
│   ├── client.py         # Studio session, folder, upload, enrichment wait, chat stream parsing
│   ├── golden.py         # load + validate golden.yaml
│   ├── metrics.py        # hit@k, MRR, abstention
│   ├── judge.py          # thin Ragas adapter (the only module importing ragas)
│   └── report.py         # result JSON, summary table, compare
└── tests/
```

## Run flow (`studio-eval run --label <name>`)

1. Sign in: `POST /api/session` with `STUDIO_EVAL_USER` / `STUDIO_EVAL_PASSWORD`.
2. Corpus: ensure a root-level folder titled `Eval corpus` (`POST /api/folders` if absent); upload each file in
   `STUDIO_EVAL_SAMPLES_DIR` not already present in it by name; wait (bounded, default 15 min) until each
   upload's enrichment job is complete. A failed enrichment aborts the run with the file name and stage.
3. For each golden entry: `POST /api/chat` `{"question", "scope": <folder id>}`; parse the SSE stream into
   answer text (concatenated `TEXT_MESSAGE_CONTENT` deltas), citations from `STATE_SNAPSHOT`
   (`docId`, `title`, `page`, `snippet`, `score`, `vectorScore`, in order), and `TOOL_CALL_END.result.rerank`.
   A `RUN_ERROR` event marks that question `error` with its message; the run continues.
4. Score (below), write results, print the summary.

`/api/chat` returning 403 (baseline mode) or 401 stops the run immediately with a clear message.

## Golden set (`eval/golden.yaml`)

```yaml
- id: pl-total                      # unique, [a-z0-9-]
  question: What is the total amount on the Polish invoice?
  answer: "<reference answer sentence>"
  evidence: "<exact substring of the extracted text>"   # required for fact
  sources: [{file: 28Polish_PL01_STP.tif, page: 1}]   # empty for unanswerable
  lang: en                          # language of the question
  kind: fact                        # fact | cross_doc | unanswerable
```

- 20–30 entries: ~15 `fact` (totals, vendor, invoice number, date), ~5 `cross_doc`, ~4 asked in the invoice's
  own language (de, fr, es, nl), ~3 `unanswerable`.
- Drafted from the Docling text extracted from each sample (read back from OpenArch and saved to
  `fixtures/extracted/<file>.md`); reviewed by the user before it is final.
- Validation (load-time and in tests): unique ids; `kind` and `lang` from the allowed sets; `sources` non-empty
  unless `unanswerable`; every source file exists in the samples directory; `fact` entries have an `evidence`
  string that appears verbatim in the source file's saved extracted text.

## Metrics

Deterministic (no grader), over answerable entries:
- **hit@k** — 1 if any citation's `(title, page)` matches an expected `(file, page)` (uploads are titled with
  their file name); k = citations returned.
- **MRR** — 1 / rank of the first matching citation, 0 if none.

Abstention:
- An answer *declines* when it contains Studio's fixed reply (`I don't have enough information in the indexed
  content to answer that.`) or one of a short list of equivalent phrasings (case-insensitive).
- **abstain_correct** — share of `unanswerable` entries that declined.
- **false_abstain** — share of answerable entries that declined.

Graded (Ragas; judge `STUDIO_EVAL_JUDGE_MODEL` at `STUDIO_EVAL_JUDGE_BASE_URL`, embeddings
`STUDIO_EVAL_EMBED_MODEL` at the same base URL):
- faithfulness, answer_relevancy, context_precision, context_recall (reference = golden `answer`;
  contexts = citation snippets). Unanswerable entries get faithfulness only.
- A grader failure on a metric records `null` for that metric on that entry; averages skip nulls and report
  the count skipped.

Aggregates: mean of each metric overall, by `kind`, and by `lang`.

## Outputs

- `eval/results/<UTC timestamp>-<label>.json`: label, timestamp, Studio URL, judge model, embed model,
  rerank statuses seen, per-entry {id, question, answer, citations, metrics, error}, aggregates.
- Console summary: overall and per-`kind` / per-`lang` table.
- `studio-eval compare <a.json> <b.json>`: aggregates side by side with deltas; entries present in only one
  file are listed.
- First live run on the current stack is committed as `eval/baselines/baseline-nomic.json`.

## Configuration

| Variable | Default |
|---|---|
| `STUDIO_EVAL_URL` | `http://localhost:8900` |
| `STUDIO_EVAL_USER` / `STUDIO_EVAL_PASSWORD` | `admin` / `password` |
| `STUDIO_EVAL_JUDGE_BASE_URL` | `http://localhost:11434/v1` |
| `STUDIO_EVAL_JUDGE_MODEL` | `qwen3` |
| `STUDIO_EVAL_EMBED_MODEL` | `nomic-embed-text` |
| `STUDIO_EVAL_SAMPLES_DIR` | `../../sample_images` (relative to `eval/`) |

## Docs & licensing

- `eval/README.md` (setup, run, compare); root README "Evaluation" section; deep dive section on method and metrics.
- `GLOSSARY.md`: *Golden set*, *Eval run*.
- `NOTICE` + README third-party table: Ragas and `qwen3`, licenses verified from upstream.
- `.env.example`: the variables above (commented).
- GitHub topics: add `evaluation` (after merge).

## Testing

Pytest in `eval/tests/`, no network or models: SSE parsing (incl. `RUN_ERROR`), golden validation (each rule),
golden-answer-in-extracted-text check over the real `golden.yaml` + fixtures, hit@k / MRR / abstention on
hand-made cases, aggregates skipping nulls, `compare`, and `judge.py` exercised with a fake Ragas adapter.

## Out of scope

UI for results, CI runs, synthetic question generation, comparing graders.
