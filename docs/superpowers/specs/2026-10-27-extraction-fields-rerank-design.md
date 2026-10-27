# Structured extraction, extracted fields, and reranking — design

Date: 2026-10-27 · Status: draft for review

## Goal

Raise Studio's answer and search quality on real (scanned, multi-language) documents, and show AI
output landing in OpenArch as metadata — in three independently shippable phases:

1. **Structured extraction** — Docling replaces Tika as the primary extractor; chunks carry real page
   numbers; citations open the source at that page.
2. **Classification + extracted fields** — each document is classified and its fields extracted into
   OpenArch metadata.
3. **Reranking + model roles** — a cross-encoder reranks retrieval results; each model job (embed,
   extract, chat, rerank) has its own setting.

## Invariants (unchanged, every phase)

- OpenArch is the system of record; no OpenArch Java module is modified.
- Every OpenArch call runs as the signed-in user; nothing reaches a model that the caller cannot read.
- New AI steps are additive: their failure never fails enrichment or search.
- `STUDIO_BASELINE_MODE=true` disables every new capability.
- Every new third-party service or model is listed with its verified license (see Docs & licensing).

## Phase 1 — Docling extraction and page-aware citations

### Service

- New compose service `docling`: `quay.io/docling-project/docling-serve-cpu`, pinned to a released
  version tag (target `v1.38.2`; verify the tag exists when implementing). CPU-only, ~4.4 GB, models
  bundled. Internal port 5001, not published.

### Extractor seam (`api/app/extraction.py`)

```python
@dataclass
class Extracted:
    markdown: str            # whole document
    pages: list[str]         # markdown per page, 1-based by position
    engine: str              # "docling" | "tika"

class Extractor(Protocol):
    async def extract(self, content: bytes, mime: str, filename: str) -> Extracted: ...
```

- `DoclingExtractor`: `POST {docling_url}/v1/convert/file` (multipart `files`), options
  `to_formats=["md"]`, `do_ocr=true`, `md_page_break_placeholder=<sentinel>`, `image_export_mode=placeholder`,
  `document_timeout` from settings. Splits `md_content` on the sentinel into `pages`.
  Response `status` of `failure` or `skipped`, any non-2xx, or a timeout raises `ExtractionFailed`.
- `TikaExtractor`: today's `PUT /tika` call, moved from `enrichment.py`; returns `pages=[text]`.
- `FallbackExtractor(primary, fallback)`: tries Docling; on `ExtractionFailed` uses Tika and returns
  `engine="tika"`. Selected by `STUDIO_EXTRACTOR` (`docling` default, `tika` = Tika only).
- The enrichment job records the engine; the Activity stage detail shows `extracted · Docling` or
  `extracted · Tika fallback`.

### Chunking (`parquet.py`)

- New `chunk_pages(pages, max_chars=1000) -> list[Chunk]` replaces `chunk_text` for enrichment.
  - Boundaries: page breaks, then Markdown headings, then blank lines; hard-wrap at `max_chars`.
  - A Markdown table is kept in one chunk when it fits; larger tables split on row boundaries.
  - Each chunk is prefixed with its nearest heading (`## Heading\n`) when one exists on that page or
    an earlier page.
  - `Chunk.page` = 1-based page index; `paragraph` = index within the page.
- Chunk IDs stay deterministic (uuid5 over index + text). The SysEmbeddings Parquet schema is
  unchanged — `location.text.page` already exists and is now populated.

### Citations

- Citation objects gain `page` (from the hit's `sysembed_location.text.page`, default 1).
- `CitationList` links to `/documents/{id}?chunk={chunkId}&page={page}`.
- The document viewer appends `#page={page}` to the PDF content URL (native browser viewer). Images
  and other formats ignore `page`.

### Capabilities

- "OCR" and "Text & metadata extraction" owner changes from "Studio + Tika" to
  "Studio + Docling (Tika fallback)"; evidence points at `extraction.py`.

### Existing documents

- Keep their current embeddings until re-enriched via the existing Activity retry.

### Settings

`STUDIO_EXTRACTOR` (`docling`), `STUDIO_DOCLING_URL` (`http://docling:5001`),
`STUDIO_DOCLING_TIMEOUT_SECONDS` (`300`).

### Tests

- Docling success with page sentinels → correct `pages`; Docling 5xx / timeout / `status=failure` →
  Tika fallback with `engine="tika"`; `STUDIO_EXTRACTOR=tika` never calls Docling.
- `chunk_pages`: page numbers carried; tables kept whole; heading prefix; hard-wrap.
- Citation includes `page`; Playwright stub asserts the citation link carries `page`.

## Phase 2 — Classification and extracted fields

### Pipeline

- New enrichment stage `classified` after `indexed`. Additive: on failure the stage is `failed` and
  retryable; the document remains searchable.

### Model call (`api/app/fields.py`)

- One chat-completions call to `STUDIO_EXTRACT_MODEL` with `response_format={"type":"json_object"}`.
  The setting is introduced here (default `llama3.2:3b`); Phase 3 moves graph extraction onto it.
- Input: first 6,000 characters of the Phase 1 Markdown, plus the vocabulary below.
- Output contract: `{"type": "<document type>", "fields": {"<name>": <value>, ...}}`.
- Prompt rules: choose an existing type when one fits, else name a new one; reuse an existing field
  name when the meaning matches; only values present in the text.

### Vocabulary (no config file)

- Built per run by an HXQL query **as the caller** over the most recent 200 documents with the
  `CinContext` mixin, reading `cinctx_contextProperties.document_type` and
  `cinctx_contextPropertyNames`. Result: `{type: [field names]}`. Names only, never values; only from
  documents the caller can read.

### Normalization

- Type and field names → `snake_case` (ASCII, `[a-z0-9_]`, max 64 chars).
- Drop empty values. Dates → ISO 8601 when parseable; numeric strings → numbers when unambiguous
  (strip currency symbols and thousands separators, keep currency as its own field if the model
  gave one). Max 25 fields; string values truncated to 500 chars.
- Unparseable model output → stage fails with "model returned invalid JSON".

### Storage in OpenArch (native `CinContext` mixin)

- Add `CinContext` to `sys_mixinTypes` (same pattern as `ensure_has_embeddings_mixin`).
- `cinctx_contextProperties` = flat map, e.g.
  `{"document_type": "invoice", "vendor_name": "…", "invoice_date": "2026-03-01", "total": 1234.5}`.
- `cinctx_contextPropertyNames` = sorted keys.
- Written as the user who ran enrichment; `OpenArchForbidden` → stage fails with
  "no write permission on this document".

### Risk check first

The first Phase 2 task verifies, against the running stack, that (a) REST accepts a free-form map in
`cinctx_contextProperties` and (b) HXQL can filter on a key inside it (e.g. `total > 1000`).

- If (a) fails: stop and revisit the storage design before building Phase 2.
- If (a) works and (b) fails: fields are still stored and shown; field-based search is dropped from
  this phase (no Studio-side filtering substitute).

### UI

- Document inspector: **Extracted fields** panel — type badge and key/value table, labelled
  "AI-extracted · Studio + model". Read-only.
- Library rows: document-type chip when present.
- Search: HXQL help gains an example field query (only if the risk check's (b) passed).

### Capabilities

- New extension "Document classification & field extraction", owner "Studio + model".
- Native "Metadata & content models" evidence references `CinContext`.

### Tests

- Parse/normalize: code fences, invalid JSON, key normalization, date/number coercion, caps.
- Vocabulary query uses caller credentials and returns names only.
- Write payload: mixin added once; properties + names shape.
- Classification failure leaves the job's other stages `done`; baseline mode gates the stage and
  the panel's API.

## Phase 3 — Reranking and model roles

### Service

- New compose service `reranker`: Hugging Face `text-embeddings-inference`, image from
  `STUDIO_RERANKER_IMAGE` (`ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9` for Apple
  Silicon / arm64, `…:cpu-1.9` for x86_64), `--model-id ${STUDIO_RERANK_MODEL}`. Weights cached in a
  named volume.
- First Phase 3 task verifies `BAAI/bge-reranker-v2-m3` loads (XLM-RoBERTa, same family as the
  listed `bge-reranker-large`). If not, default to `BAAI/bge-reranker-base`.

### Reranker seam (`api/app/rerank.py`)

- `rerank(query, texts) -> list[float]` via `POST {reranker_url}/rerank`
  (`{"query": ..., "texts": [...]}` → `[{"index", "score"}]`).
- Semantic search, keyword search, and chat retrieval fetch `top_k * 3` (cap 30) candidates from the
  existing ACL-filtered OpenArch kNN, rerank, and keep `top_k`.
- Fallback: reranker unset (`STUDIO_RERANKER_URL` empty), non-2xx, or timeout (3 s) → vector order,
  trace marks `rerank: skipped (<reason>)`.
- Citation `score` = rerank score when reranked; the retrieval trace shows vector and rerank scores.

### Model roles (`config.py`)

| Role | Setting | Default |
|---|---|---|
| Embed | `STUDIO_EMBEDDING_MODEL` | `nomic-embed-text` |
| Extract (graph, classification, fields) | `STUDIO_EXTRACT_MODEL` | `llama3.2:3b` |
| Chat | `STUDIO_CHAT_MODEL` | `llama3.2:3b` (was `llama3.1`) |
| Rerank | `STUDIO_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` |

- `STUDIO_GRAPH_MODEL` is accepted as a deprecated alias for `STUDIO_EXTRACT_MODEL`.
- All LLM roles share `STUDIO_MODEL_BASE_URL`.
- Startup warm-up: a background task sends one minimal request to the extract and chat models;
  failures are logged, never block startup.

### Capabilities

- New extension "Reranking", owner "Studio + model"; baseline mode gates it (search falls back to
  vector order).

### Tests

- Reorders and truncates to `top_k`; fallback on timeout / 5xx / unset URL; trace carries both
  scores; deprecated `STUDIO_GRAPH_MODEL` alias; warm-up is non-blocking and swallows errors.

## Docs & licensing (definition of done for every phase)

Each phase ships its doc updates in the same push:

- `README.md`: architecture diagram, services table, environment variables, run steps (model pulls,
  reranker image per architecture), third-party components table.
- `NOTICE`: third-party components with license and upstream link — Docling / docling-serve and their
  layout/table models, Apache Tika, Ollama, `nomic-embed-text`, Llama 3.2 (Llama Community License,
  "Built with Llama" attribution), text-embeddings-inference, the reranker model. Each license is
  verified from the upstream repository or model card at implementation time, not from memory.
- `docs/TECHNICAL-DEEP-DIVE.md`: pipeline stages, extractor + fallback, page-aware citations,
  extracted-field storage, reranking, model roles.
- `GLOSSARY.md`: Extractor, Document type, Extracted fields, Rerank, Model role.
- `.env.example` and `AGENTS.md` updated.
- `studio-issues/01` and `/02` marked resolved with references to the fixes (Phase 3).
- GitHub repository About: description and topics set with `gh repo edit` — exact text shown to the
  user for approval before applying.

## Out of scope

- Bounding-box highlighting inside the PDF (page-level jump only).
- Editing extracted fields in the UI.
- A configured document-type schema.
- Marker / Datalab models, LightRAG.
- GPU images.
