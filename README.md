# OpenArch Studio

A self-contained proof-of-concept that shows **OpenArch as a complete, permission-aware
AI-ready content platform** — and makes explicit which capabilities are OpenArch's own and
which are added on top.

One workflow, end to end:

> **sign in → upload → enrich → inspect → search → ask → open citation**

Studio is an add-on to the public [Hyland/OpenArch](https://github.com/Hyland/OpenArch)
deployment: clone it into an OpenArch checkout and one `docker compose up` starts both — see
[Run it on Hyland OpenArch](#run-it-on-hyland-openarch).

Upload a document; Studio stores it in OpenArch, extracts text with Docling (Tika as fallback),
chunks and embeds it with a local model, and writes the vectors back as an OpenArch `SysEmbeddings` child. Then search
it four ways and ask an agent questions whose answers are grounded in — and cited from — only the
content you're allowed to read.

After indexing, a small local model also classifies each document and extracts typed fields
(vendor, date, total, …). They are written to OpenArch's native `CinContext` mixin, shown in the
document inspector and as type chips in the Library, and searchable with HXQL, for example
`SELECT * FROM SysContent WHERE cinctx_contextProperties.total > 1000`.
Field value types are fixed by field name: amount-like names (`total`, `tax_amount`, `quantity`)
are stored as decimals (floats), while id/number/rate/date/currency-style names (`vat_id`,
`tax_rate`, `total_currency`) and all others stay text, so HXQL range queries work on amount-like
fields only. An OpenArch index that already saw a field with a different type needs that document
re-enriched (or a fresh index), because OpenSearch can't change a field's type in place.
Retrying or re-enriching a document replaces its embeddings rather than adding a second set.

## What's OpenArch vs. what Studio adds

| OpenArch native | Studio / open-source extension |
|---|---|
| Document & binary storage, metadata, content models | Visual content workspace |
| ACLs & effective permissions | Permission visualization |
| Keyword & advanced HXQL queries | Guided search interface |
| `SysEmbeddings` storage & vector search | Docling extraction (Tika fallback), chunking, embedding (Ollama) |
| Hybrid search (kNN + BM25, RRF via `chunkFTS`) | Hybrid mode in Search; hybrid retrieval for Ask |
| Permission-aware retrieval (runs as the caller) | RAG orchestration & streaming cited chat |
| OpenSearch indexing | Citations & retrieval trace |
| REST / OpenAPI contract | Same-origin, memory-only session gateway |

The in-app **Capability map** (`/capabilities`) is the live version of this table. Studio never
labels Docling/Tika extraction, embedding, model inference, or chat as native OpenArch features.

## Architecture

```
Browser (React/Vite SPA)
      │  same-origin
      ▼
 nginx ──► Studio API (FastAPI BFF)
                 ├─► OpenArch   (documents, ACLs, SysEmbeddings, vector search)
                 ├─► Docling     (layout-aware extraction + OCR → Markdown)
                 │     └─ falls back to ─► Apache Tika (text + metadata extraction)
                 ├─► Ollama      (OpenAI-compatible embeddings + chat)
                 └─► Reranker    (text-embeddings-inference cross-encoder; optional)
```

| Service | Image | Role |
|---|---|---|
| `studio-web` | `./web` (nginx) | SPA on `${STUDIO_PORT:-8900}`; proxies `/api/*`. |
| `studio-api` | `./api` (FastAPI) | Session gateway, enrichment, search, RAG, graph. |
| `openarch-app` | OpenArch base compose | System of record. |
| `docling` | `quay.io/docling-project/docling-serve-cpu:v1.38.2` | Primary extractor. Not published to the host. |
| `tika` | `apache/tika:2.9.2.1-full` | Fallback extractor (Tesseract OCR). |
| `ollama` | `ollama/ollama:latest` | Local embeddings and chat. |
| `reranker` | `ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9` (`${STUDIO_RERANKER_IMAGE}`) | Cross-encoder reranking of search and chat candidates. Optional. |

- Credentials are held in **server memory only**, keyed by an HTTP-only cookie. A restart drops
  every session; nothing is written to the browser.
- Every OpenArch call is made as the signed-in user, so ACLs stay in force through search and chat.
- No OpenArch Java module is modified — this stack lives entirely under `pocs/openarch-studio/`.

## Run it on Hyland OpenArch

Studio runs on top of the standard OpenArch deployment from
[Hyland/OpenArch](https://github.com/Hyland/OpenArch). Its Compose file includes that repo's
`docker-compose.yml` (OpenArch app on `8080`, MongoDB, OpenSearch, Dashboards), so Studio must be
cloned into `pocs/openarch-studio` inside an OpenArch checkout. Nothing in OpenArch is modified.

Requires Docker and Git.

```bash
# 1. OpenArch, from Hyland's GitHub
git clone https://github.com/Hyland/OpenArch && cd OpenArch

# 2. Studio, inside it
git clone https://github.com/haaldinger/openarch-studio pocs/openarch-studio
cd pocs/openarch-studio

# 3. Configure and start OpenArch + Studio together
cp .env.example .env                 # sets OPENARCH_VERSION=1.0.60 (public image, no login)
docker compose up -d --build

# one-time: pull the local models Ollama will serve
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.2:3b   # chat, graph, classification + field extraction

# open the UI
open http://localhost:8900
```

OpenArch itself stays on its usual endpoints: REST/Swagger at
`http://localhost:8080/swagger-ui/index.html` (basic auth `admin` / `password`), OpenSearch
Dashboards at `http://localhost:5601`.

Sign in with an OpenArch user (the default dev store includes `admin` / `password`). Upload a PDF,
DOCX, TXT, Markdown, HTML, or image file, watch it enrich on the **Activity** page, then try
**Search** and **Ask**. The first Docling conversion is slow while it loads its models.

### Extraction settings

| Variable | Default | Purpose |
|---|---|---|
| `STUDIO_EXTRACTOR` | `docling` | `docling` (Tika fallback on failure) or `tika` only. |
| `STUDIO_DOCLING_URL` | `http://docling:5001` | docling-serve base URL. |
| `STUDIO_DOCLING_TIMEOUT_SECONDS` | `300` | Per-document Docling timeout; also caps docling-serve's sync wait. |

### Model roles

| Role | Variable | Default | Used for |
|---|---|---|---|
| Embed | `STUDIO_EMBEDDING_MODEL` | `nomic-embed-text` | Chunk and query embeddings. |
| Extract | `STUDIO_EXTRACT_MODEL` | `llama3.2:3b` | Knowledge graph, document classification, field extraction. |
| Chat | `STUDIO_CHAT_MODEL` | `llama3.2:3b` | Grounded answers in **Ask**. |
| Rerank | `STUDIO_RERANK_MODEL` | `BAAI/bge-reranker-base` | Cross-encoder loaded by the `reranker` service. |

All LLM roles share `STUDIO_MODEL_BASE_URL`. `STUDIO_GRAPH_MODEL` is a deprecated alias for
`STUDIO_EXTRACT_MODEL`; the API and Compose use it only when `STUDIO_EXTRACT_MODEL` is unset. `llama3.1` is a
heavier alternative for `STUDIO_CHAT_MODEL` on GPU hosts (`ollama pull llama3.1` first); it is
unusably slow on CPU. At startup the API pings the extract and chat models in the background so the
first request isn't cold (skipped in baseline mode); a failed ping is logged and never blocks startup.

If the extract model call fails, only the `classified` stage fails (retry from **Activity**); the
document stays searchable.

### Reranking settings

| Variable | Default | Purpose |
|---|---|---|
| `STUDIO_RERANKER_IMAGE` | `ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9` | Reranker image. Use `…:cpu-1.9` on x86_64 hosts. |
| `STUDIO_RERANKER_URL` | `http://reranker:80` (Compose default; the API's built-in default is empty, which disables reranking) | Where the API reaches the reranker. Set it empty (`STUDIO_RERANKER_URL=`) to disable reranking. |
| `STUDIO_RERANK_MODEL` | `BAAI/bge-reranker-base` | Model the reranker downloads on first start (cached in the `reranker-models` volume). |
| `STUDIO_HYBRID_SEARCH` | `true` | **Ask** retrieves with OpenArch hybrid search (kNN + BM25 over chunk text, merged with RRF). `false` = vector only. |

**Search** has a **Hybrid** mode next to Keyword, Semantic and HXQL. It sends the query to OpenArch's
`POST /api/query/embeddings` with both the vector and `chunkFTS`, so exact terms such as invoice
numbers count as well as meaning. Hybrid search needs OpenArch 1.0.60 or later.

Semantic search, hybrid search and **Ask** fetch `max(top_k, min(top_k * 2, 12))` candidates from OpenArch (as the
caller, so ACLs apply) and rerank them. If the reranker is disabled or fails, results keep their vector
order and the trace shows `skipped (<reason>)`. Keyword search fetches 50 hits, keeps those containing the query
terms, and reranks the first `max(limit, 12)` of them. If the reranker is disabled, slow (5 s timeout),
or unreachable, results keep vector order and the trace says why (`skipped (…)`). HXQL search is not
reranked. `BAAI/bge-reranker-v2-m3` is more accurate but was OOM-killed or too slow on Docker CPU.

To use a hosted OpenAI-compatible provider instead of Ollama, set `STUDIO_MODEL_BASE_URL` (and the
provider key) on the `studio-api` service and skip the `ollama pull` steps.

## Develop

```bash
# API (Python)
cd api && python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q

# Web (TypeScript)
cd web && npm install
npm test            # unit tests (Vitest)
npm run build       # typecheck + production build
npm run dev         # http://localhost:5173, proxies /api to localhost:8800
```

## Supported formats

PDF, DOCX, TXT, Markdown, HTML (`.html`, `.htm`), and scanned images (TIFF, PNG, JPEG, GIF, BMP).
Docling extracts PDF, DOCX, HTML, Markdown, TXT, and PNG, JPEG, and TIFF images (OCR for scanned images). GIF and BMP are accepted at upload, but Docling support
for them is not verified. If Docling can't process a file, Tika takes over. Unsupported types are
rejected at upload. Extraction or embedding failures leave the original document safely stored in
OpenArch and are retryable from **Activity**.

Citations carry the source page. Clicking one opens `/documents/{id}?page=N`, and PDFs open at that
page in the browser's native viewer.

## Evaluation

`eval/` holds a harness that asks Studio a golden set of 28 questions (English, German, French,
Spanish, Dutch) over the sample documents and scores retrieval, abstention and answer quality, so
changes to extraction, chunking, embedding or reranking can be compared run to run. Answer quality
is graded by Ragas with a local `qwen3` model. See [`eval/README.md`](eval/README.md) for setup and
usage.

```bash
cd eval && python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/studio-eval run --label my-change
```

Baseline results (`eval/baselines/baseline-nomic.json`, overall aggregates):

| Metric | Mean | n |
| --- | --- | --- |
| hit | 0.720 | 25 |
| mrr | 0.539 | 25 |
| evidence_hit | 0.450 | 20 |
| evidence_mrr | 0.278 | 20 |
| false_abstain | 0.680 | 25 |
| abstain_correct | 1.000 | 3 |
| faithfulness | 0.396 | 28 |
| answer_relevancy | 0.232 | 25 |
| context_precision | 0.309 | 25 |
| context_recall | 0.480 | 25 |

Run note: "studio embed=nomic-embed-text chat=llama3.2:3b rerank=bge-reranker-base"; all 28 questions
reranked, 0 errors; judge `qwen3`. The right invoice is retrieved for about 72%
of answerable questions, but the chunk containing the answer only about 45% of the time. Ask
(`llama3.2:3b`) declines 68% of answerable questions, so answer generation and chunk-level retrieval
are the weakest links; the next sub-projects (multilingual embeddings, hybrid search) target
`evidence_hit`.

### Hybrid search vs. baseline

[`eval/baselines/hybrid-1060.json`](eval/baselines/hybrid-1060.json): OpenArch 1.0.60, Ask with hybrid
search (`chunkFTS`, kNN + BM25 merged with RRF), otherwise the same models. Compare with
`studio-eval compare eval/baselines/baseline-nomic.json eval/baselines/hybrid-1060.json`.

| Metric | Baseline | Hybrid | Change |
|---|---|---|---|
| hit | 0.720 | 0.840 | +0.120 |
| evidence_hit | 0.450 | 0.600 | +0.150 |
| evidence_mrr | 0.278 | 0.349 | +0.071 |
| false_abstain (lower is better) | 0.680 | 0.600 | −0.080 |
| faithfulness | 0.396 | 0.457 | +0.061 |
| answer_relevancy | 0.232 | 0.378 | +0.146 |
| context_precision | 0.309 | 0.357 | +0.048 |
| context_recall | 0.480 | 0.600 | +0.120 |

The baseline ran on OpenArch 1.0.0, so the OpenArch version differs as well as retrieval; one rerank
call timed out in the hybrid run.

## POC limitations (deferred, by design)

- Memory-backed Basic-auth sessions, not production identity (no OIDC, no multi-instance store).
- Single-node, in-memory enrichment jobs (no durable queue); readiness is reconstructed from
  OpenArch's `SysEmbeddings` children after a restart.
- Knowledge-graph / ontology features, external connectors, and admin UIs for users/groups/
  vocabularies are out of scope for this first release.

## Interoperability

Studio writes embeddings in the same `SysEmbeddings` Parquet shape OpenArch's own ingesters use, so
a document enriched here is queryable by the broader
[content-lake deployment](https://github.com/aborroy/content-lake-app-deployment) and vice versa.

## Third-party components

Licenses below were checked against each upstream repository or model card. Docling image
components were checked at the versions the image pins (docling-serve `v1.38.2` → Docling
`2.142.1`, rapidocr `3.10.0`, easyocr `1.7.2`), except the layout-heron models (including the ONNX
export) and DocumentFigureClassifier v2.5: Docling pins those to the floating revision `main`, so they
were checked at `main` (pinned revision not confirmed). Tika, Ollama, nomic-embed-text and Llama are
not in the Docling image and were checked at their default branch or model card.
text-embeddings-inference was checked at tag `v1.9.0`; the `cpu-1.9` / `cpu-arm64-1.9` image tags
float across 1.9.x patch releases, so the exact patch is not pinned. `BAAI/bge-reranker-base` was
checked at revision `2cfc18c`, but the reranker downloads the model's default branch. The
evaluation harness's Ragas was checked at its pinned tag `v0.4.3`; its grader `qwen3` is pulled
through Ollama, whose tag floats (currently the 8B variant), so its license was checked on the
Qwen/Qwen3-8B model card at revision `b968826` and the exact weights are not pinned.

| Component | Role | License | Link |
|---|---|---|---|
| docling-serve | Extraction service (HTTP API around Docling) | MIT | [LICENSE](https://github.com/docling-project/docling-serve/blob/v1.38.2/LICENSE) |
| Docling | Document conversion library | MIT | [LICENSE](https://github.com/docling-project/docling/blob/v2.142.1/LICENSE) |
| docling-layout-heron (and its ONNX export) | Docling layout-analysis model | Apache-2.0 (checked at `main`, pinned revision not confirmed) | [model card](https://huggingface.co/docling-project/docling-layout-heron), [ONNX card](https://huggingface.co/docling-project/docling-layout-heron-onnx) |
| TableFormer (`docling-models` v2.3.0) | Docling table-structure model | CDLA-Permissive-2.0 | [model card](https://huggingface.co/docling-project/docling-models/blob/v2.3.0/README.md) |
| DocumentFigureClassifier v2.5 | Docling picture-classifier model | MIT (checked at `main`, pinned revision not confirmed) | [model card](https://huggingface.co/docling-project/DocumentFigureClassifier-v2.5) |
| RapidOCR | OCR engine in the Docling image | Apache-2.0 | [LICENSE](https://github.com/RapidAI/RapidOCR/blob/v3.10.0/LICENSE) |
| PP-OCR models (via RapidOCR) | OCR detection/recognition models, converted from PaddleOCR | Apache-2.0 | [RapidOCR README, Models](https://github.com/RapidAI/RapidOCR/blob/v3.10.0/README.md#-license) |
| EasyOCR | OCR engine in the Docling image | Apache-2.0 (code) | [LICENSE](https://github.com/JaidedAI/EasyOCR/blob/v1.7.2/LICENSE) |
| Apache Tika | Fallback text and metadata extraction | Apache-2.0 | [LICENSE](https://github.com/apache/tika/blob/main/LICENSE.txt) |
| Ollama | Local model runtime | MIT | [LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE) |
| nomic-embed-text | Embedding model | Apache-2.0 | [model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) |
| Llama 3.1 | Optional chat model (GPU hosts) | Llama 3.1 Community License | [license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE) |
| Llama 3.2 | Default chat and extract model | Llama 3.2 Community License | [license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE) |
| text-embeddings-inference | Reranker service | Apache-2.0 | [LICENSE](https://github.com/huggingface/text-embeddings-inference/blob/v1.9.0/LICENSE) |
| BAAI/bge-reranker-base | Reranking model | MIT | [model card](https://huggingface.co/BAAI/bge-reranker-base/tree/2cfc18c9415c912f9d8155881c133215df768a70), [FlagEmbedding LICENSE](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE) |
| Ragas | Evaluation metrics library (`eval/`) | Apache-2.0 (v0.4.3) | [LICENSE](https://github.com/explodinggradients/ragas/blob/v0.4.3/LICENSE) |
| Qwen3 (`qwen3`) | Evaluation grader model (`eval/`) | Apache-2.0 (Qwen3-8B at revision `b968826`; Ollama tag floats, not pinned) | [model card](https://huggingface.co/Qwen/Qwen3-8B/tree/b968826d9c46dd6066d109eabc6255188de91218) |

Bundled in the Docling image, license not yet verified: EasyOCR model weights (`craft_mlt_25k`,
`english_g2`, `latin_g2`).

**Built with Llama.**

## License

Copyright 2026 Hyland. OpenArch Studio is released under the [Apache License 2.0](LICENSE), the
same license as OpenArch.
