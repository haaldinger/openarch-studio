# Extraction, Extracted Fields & Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docling-based page-aware extraction, LLM document classification + field extraction stored in OpenArch, and cross-encoder reranking with per-role model settings — shipped as three independently demoable phases.

**Architecture:** Each capability is a small seam in `studio-api` (`extraction.py`, `fields.py`, `rerank.py`) wired into the existing enrichment pipeline, search, and agent. New runtimes (`docling`, `reranker`) are Compose services. OpenArch stays the system of record; every OpenArch call uses the caller's credentials.

**Tech Stack:** FastAPI, httpx, respx, pytest (api); React + TypeScript, Vitest, Playwright (web); Docker Compose; docling-serve; Hugging Face text-embeddings-inference; Ollama.

**Spec:** `docs/superpowers/specs/2026-10-27-extraction-fields-rerank-design.md`

All paths below are relative to `pocs/openarch-studio/`. API tests run with `cd api && .venv/bin/pytest -q`; web tests with `cd web && npm test -- --run`.

## Global Constraints

- No OpenArch Java module is modified.
- Every OpenArch call runs with the caller's `Credentials`; nothing reaches a model that the caller cannot read.
- New AI steps are additive: their failure never fails enrichment or search.
- `STUDIO_BASELINE_MODE=true` disables every new capability.
- Docling image: `quay.io/docling-project/docling-serve-cpu`, pinned version tag (target `v1.38.2`).
- Reranker image: `STUDIO_RERANKER_IMAGE`, `ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9` (arm64) / `…:cpu-1.9` (x86_64).
- Model defaults: embed `nomic-embed-text`; extract `llama3.2:3b`; chat `llama3.2:3b`; rerank `BAAI/bge-reranker-v2-m3`.
- Field limits: max 25 fields; string values ≤ 500 chars; names `snake_case` `[a-z0-9_]`, ≤ 64 chars; classifier input = first 6,000 chars; vocabulary = 200 most recent `CinContext` docs.
- Rerank: candidates `min(top_k * 3, 30)`, timeout 3 s.
- Every new third-party service/model appears in `NOTICE` and the README third-party table with a license verified from its upstream repo or model card.
- Each phase ships its doc updates (README, NOTICE, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `.env.example`, `AGENTS.md`) in the same push. Pushing to `origin` requires the user's go-ahead.

## Review Focus

1. Docling returns `status: "partial_success"` or an empty `md_content` → partial with text is kept; empty text falls back to Tika (Task 1).
2. Model returns non-scalar field values (lists, nested objects) or keys with accents/symbols (`numéro_facture`, `Total ($)`) → lists of scalars join with `, `, objects drop; keys transliterate to ASCII, keys that normalize to empty drop (Task 7).
3. Reranker returns fewer results than texts, or indexes out of order → scores map by `index`; any missing index → vector order (Task 13).
4. Hits from documents enriched before this change have no `sysembed_location` → citation `page` is `1`, not an error (Task 4).
5. Classification retried by a user without write permission → `classified` stage `failed` with "no write permission on this document"; job state stays `complete` (Task 9).

---

## Phase 1 — Docling extraction and page-aware citations

### Task 1: Extractor seam and Docling service

**Files:**
- Create: `api/app/extraction.py`
- Modify: `api/app/config.py`, `compose.yaml`, `.env.example`
- Test: `api/tests/test_extraction.py`

**Interfaces:**
- Produces:
  - `@dataclass Extracted(markdown: str, pages: list[str], engine: str)`
  - `class ExtractionFailed(Exception)`
  - `class DoclingExtractor(settings)`, `class TikaExtractor(settings)`, `class FallbackExtractor(primary, fallback)` — each with `async def extract(self, content: bytes, mime: str, filename: str) -> Extracted`
  - `def build_extractor(settings: Settings) -> FallbackExtractor | TikaExtractor`
  - `PAGE_BREAK = "<!-- studio:page-break -->"`
  - Settings: `extractor: str = "docling"`, `docling_url: str = "http://docling:5001"`, `docling_timeout_seconds: int = 300`

- [ ] **Step 1: Write failing tests** in `api/tests/test_extraction.py` (respx; `DOCLING = "http://docling.test/v1/convert/file"`, `TIKA = "http://tika.test/tika"`):

```python
async def test_docling_splits_pages_on_break():
    # md_content = f"# Inv\nA{PAGE_BREAK}B", status success
    result = await build_extractor(settings).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "docling"
    assert result.pages == ["# Inv\nA", "B"]
    assert PAGE_BREAK not in result.markdown

async def test_docling_request_asks_for_markdown_ocr_and_page_breaks():
    # inspect respx call: multipart has "files"; form fields to_formats=md, do_ocr=true,
    # md_page_break_placeholder=PAGE_BREAK, image_export_mode=placeholder
    ...

async def test_falls_back_to_tika_on_docling_5xx(): ...           # engine == "tika", pages == [tika text]
async def test_falls_back_to_tika_on_docling_timeout(): ...       # respx side_effect httpx.ReadTimeout
async def test_falls_back_to_tika_on_status_failure(): ...        # status "failure"
async def test_partial_success_with_text_is_kept(): ...           # status "partial_success", engine == "docling"
async def test_empty_markdown_falls_back_to_tika(): ...           # md_content "   "
async def test_tika_only_mode_never_calls_docling(): ...          # settings.extractor="tika"; docling route not called
```

- [ ] **Step 2: Run** `cd api && .venv/bin/pytest tests/test_extraction.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement `api/app/extraction.py`.** `DoclingExtractor` posts multipart `files=(filename, content, mime)` with form fields above plus `document_timeout`; raises `ExtractionFailed` on non-2xx, `httpx.TimeoutException`, `status in {"failure","skipped"}`, or blank `md_content`. Pages = `md_content.split(PAGE_BREAK)` stripped; `markdown = "\n\n".join(pages)`. `TikaExtractor` is the current `EnrichmentService._extract` body, returning `pages=[text]`. Add the three settings to `config.py`.
- [ ] **Step 4: Add the Compose service** `docling` (image pinned per Global Constraints; verify the tag exists with `docker manifest inspect`; no published port), and `STUDIO_EXTRACTOR`, `STUDIO_DOCLING_URL` to `studio-api` env and `.env.example`.
- [ ] **Step 5: Run** the test file → PASS; full suite `.venv/bin/pytest -q` → PASS.
- [ ] **Step 6: Commit** `feat(api): Docling extractor with Tika fallback`.

### Task 2: Page- and structure-aware chunking

**Files:**
- Modify: `api/app/parquet.py`
- Test: `api/tests/test_parquet.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `def chunk_pages(pages: list[str], *, max_chars: int = 1000) -> list[Chunk]` (existing `Chunk`; `page` 1-based, `paragraph` 1-based within page; ids `uuid5(_CHUNK_NAMESPACE, f"{index}:{text}")` with a global running index). `chunk_text` stays for existing callers.

- [ ] **Step 1: Write failing tests:**

```python
def test_chunk_pages_carries_page_numbers():
    chunks = chunk_pages(["Alpha.", "Beta."])
    assert [(c.page, c.paragraph) for c in chunks] == [(1, 1), (2, 1)]

def test_heading_prefixes_following_chunks_across_pages():
    chunks = chunk_pages(["## Totals\n\nNet 10", "Gross 12"])
    assert chunks[0].text == "## Totals\nNet 10"
    assert chunks[1].text == "## Totals\nGross 12"

def test_table_kept_whole_when_it_fits():
    table = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    assert any(c.text.endswith(table) for c in chunk_pages([f"Intro\n\n{table}"]))

def test_oversized_table_splits_on_row_boundaries():
    rows = "\n".join(f"| {i} | {'x' * 40} |" for i in range(60))
    table = "| n | v |\n|---|---|\n" + rows
    for c in chunk_pages([table], max_chars=500):
        assert len(c.text) <= 500
        assert all(line.startswith("|") for line in c.text.splitlines())

def test_long_paragraph_hard_wraps():
    assert all(len(c.text) <= 1000 for c in chunk_pages(["x" * 2500]))

def test_blank_pages_produce_no_chunks():
    assert chunk_pages(["", "   "]) == []
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `chunk_pages`.** Per page: split into blocks on blank lines; a block whose lines all start with `|` is a table; a block starting with `#` updates the current heading (carried across pages) and is not emitted alone. Prefix `f"{heading}\n"` when a heading is set; wrap so prefix + body ≤ `max_chars` (tables wrap on row lines, repeating no header).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): page- and heading-aware chunking`.

### Task 3: Wire the extractor into enrichment

**Files:**
- Modify: `api/app/enrichment.py`, `api/app/main.py`, `api/tests/test_enrichment.py`, `api/tests/conftest.py`
- Test: `api/tests/test_enrichment.py`

**Interfaces:**
- Consumes: `build_extractor`, `Extracted`, `chunk_pages`.
- Produces: `EnrichmentService.__init__(settings, store=None, graph=None, extractor=None)`; `extract_text(content, mime) -> str` now returns `Extracted.markdown`; `extracted` stage detail is `"Docling · {n} chars"` or `"Tika fallback · {n} chars"` (`"Tika · {n} chars"` when `extractor="tika"`); graph extraction receives `markdown`.

- [ ] **Step 1: Update fixtures** — `conftest.settings` and `test_enrichment.make_service` set `extractor="tika"` so existing tests keep mocking Tika only.
- [ ] **Step 2: Write failing tests:**

```python
async def test_docling_pages_reach_parquet_locations(): ...
    # settings extractor="docling"; docling returns two pages; capture the uploaded parquet
    # via respx call content; read with pyarrow; assert location.text.page values == [1, 2]

async def test_extracted_stage_names_the_engine(): ...
    # docling 500 -> tika OK; job.stage("extracted").detail.startswith("Tika fallback")
```

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement:** replace `_extract` with `self._extractor.extract(content, mime, job.filename)`; use `chunk_pages(extracted.pages)`; set stage detail; pass `extracted.markdown` to graph.
- [ ] **Step 5: Run** full api suite → PASS.
- [ ] **Step 6: Commit** `feat(api): enrichment uses Docling pages`.

### Task 4: Page-aware citations

**Files:**
- Modify: `api/app/agent.py` (`Evidence`), `api/app/chat.py`, `api/app/search.py`, `web/src/types.ts`, `web/src/components/CitationList.tsx`, `web/src/pages/DocumentPage.tsx`, `web/e2e/studio.spec.ts`
- Test: `api/tests/test_agent.py`, `api/tests/test_search.py`, `web/tests/ask.test.tsx`

**Interfaces:**
- Produces: `def hit_page(hit: dict) -> int` in `agent.py` (reads `hit["sysembed_location"]["text"]["page"]`, default `1`); `Evidence.page: int = 1`; chat citation dict and search result dict gain `"page"`; TS `Citation.page: number`, `SearchResult.page?: number`; route `/documents/:docId?chunk=…&page=N`; `DocumentViewer({ docId, mime, page })` uses `` `${contentUrl(docId)}#page=${page}` `` for PDFs.

- [ ] **Step 1: Write failing tests:**

```python
def test_hit_page_reads_location_and_defaults_to_one():
    assert hit_page({"sysembed_location": {"text": {"page": 3}}}) == 3
    assert hit_page({}) == 1

async def test_chat_citation_carries_page(): ...      # STATE_SNAPSHOT citations[0]["page"] == 2
async def test_semantic_result_carries_page(): ...    # results[0]["page"] == 2
```

```tsx
it("links a citation to its page", () => {
  render(<CitationList citations={[{ docId: "d1", chunkId: "c1", snippet: "s", score: 0.5, page: 4 }]} />, { wrapper: MemoryRouter });
  expect(screen.getByRole("link")).toHaveAttribute("href", "/documents/d1?chunk=c1&page=4");
});
```

- [ ] **Step 2: Run** api + web tests → FAIL.
- [ ] **Step 3: Implement** the interfaces above; `DocumentPage` reads `page` via `useSearchParams`, opens the `content` tab when `page` is present, and passes it to `DocumentViewer`.
- [ ] **Step 4: Update** the Playwright stub citation to include `page: 2` and assert the link's `href` contains `page=2`.
- [ ] **Step 5: Run** `pytest -q`, `npm test -- --run`, `npm run build` → PASS.
- [ ] **Step 6: Commit** `feat: citations open the source at the cited page`.

### Task 5: Phase 1 capabilities, docs, licenses, live check

**Files:**
- Modify: `api/app/capabilities.py`, `api/tests/test_capabilities.py`, `README.md`, `NOTICE`, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `AGENTS.md`, `.env.example`

- [ ] **Step 1: Test** `test_extraction_capabilities_name_docling`: entries "Scanned-image OCR" and "Text & metadata extraction" have owner `"Studio + Docling (Tika fallback)"` and evidence `"extraction.py"`; `_RUNTIMES` contains `{"name": "Docling", ...}`. Run → FAIL; implement; run → PASS.
- [ ] **Step 2: Verify licenses** from upstream (repo LICENSE files / model cards): docling-serve, docling, the Docling layout and TableFormer models, Apache Tika, Ollama, `nomic-embed-text`, Llama 3.1 / 3.2 (Llama Community License; "Built with Llama"). Record each with URL.
- [ ] **Step 3: Docs.** README: architecture diagram adds Docling, services table, env vars (`STUDIO_EXTRACTOR`, `STUDIO_DOCLING_URL`, `STUDIO_DOCLING_TIMEOUT_SECONDS`), "Third-party components" table, "Built with Llama". NOTICE: third-party section mirroring the table. Deep dive: extractor + fallback + page-aware chunking + citations. GLOSSARY: *Extractor*. AGENTS.md: `docs/` line unchanged; mention `extraction.py` in the `api/` line.
- [ ] **Step 4: Live check.** `docker compose up -d --build`; upload `../../sample_images/01-English_GB01_STP.tif` and a multi-page PDF; confirm Activity shows `extracted · Docling`, and that an Ask citation opens the PDF at its page (browser). Record results in the progress ledger.
- [ ] **Step 5: Commit** `docs: Phase 1 — Docling extraction, licenses`; ask the user before `git push`.

---

## Phase 2 — Classification and extracted fields

### Task 6: Risk check — CinContext storage and HXQL filtering

**Files:** none committed (record findings in the progress ledger).

- [ ] **Step 1:** Against the running stack as `admin`, add `CinContext` to a test document's `sys_mixinTypes` and `PUT` `{"cinctx_contextProperties": {"document_type": "invoice", "total": 1234.5}, "cinctx_contextPropertyNames": ["document_type", "total"]}`. Expected: 200 and the values read back on `GET`.
- [ ] **Step 2:** `POST /api/query` with `SELECT * FROM SysContent WHERE cinctx_contextProperties/total > 1000` (try `/`, `.` and `:` path forms). Record which (if any) works.
- [ ] **Step 3: Decide.** If Step 1 fails → stop, report to the user, do not start Task 7. If only Step 2 fails → set `FIELD_QUERY = None` for Task 11 (no HXQL example). Otherwise record the working syntax as `FIELD_QUERY`.

### Task 7: Field parsing and normalization

**Files:**
- Create: `api/app/fields.py`
- Test: `api/tests/test_fields.py`

**Interfaces:**
- Produces:
  - `@dataclass ClassifiedFields(document_type: str, fields: dict[str, str | int | float])`
  - `def normalize_name(raw: str) -> str` (NFKD → ASCII, lowercase, non-`[a-z0-9]` runs → `_`, strip `_`, ≤ 64)
  - `def parse_classification(raw: str) -> ClassifiedFields` (raises `ValueError("model returned invalid JSON")`)

- [ ] **Step 1: Write failing tests:**

```python
def test_normalize_name():
    assert normalize_name("Numéro Facture") == "numero_facture"
    assert normalize_name("Total ($)") == "total"
    assert normalize_name("!!!") == ""

def test_parse_tolerates_code_fences():
    r = parse_classification('```json\n{"type":"Invoice","fields":{"Vendor Name":"ACME"}}\n```')
    assert r.document_type == "invoice" and r.fields == {"vendor_name": "ACME"}

def test_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_classification("not json")

def test_values_coerced():
    r = parse_classification('{"type":"invoice","fields":{"total":"$1,234.50","date":"03/01/2026","items":["a","b"],"nested":{"x":1},"empty":""}}')
    assert r.fields == {"total": 1234.5, "date": "2026-03-01", "items": "a, b"}

def test_caps():
    many = {f"f{i}": "v" * 900 for i in range(40)}
    r = parse_classification(json.dumps({"type": "x", "fields": many}))
    assert len(r.fields) == 25 and all(len(v) == 500 for v in r.fields.values())

def test_missing_type_becomes_other():
    assert parse_classification('{"fields":{}}').document_type == "other"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Dates: accept ISO, `DD.MM.YYYY`, `MM/DD/YYYY`, `YYYY/MM/DD` via `datetime.strptime` attempts → `date.isoformat()`; otherwise keep the string. Numbers: strip currency symbols, spaces and thousands separators; convert when the remainder is a plain decimal.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): classification parsing and normalization`.

### Task 8: FieldsService — vocabulary, model call, OpenArch write

**Files:**
- Modify: `api/app/fields.py`, `api/app/openarch.py`, `api/app/config.py`
- Test: `api/tests/test_fields.py`, `api/tests/test_openarch.py`

**Interfaces:**
- Consumes: `ClassifiedFields`, `parse_classification`, `OpenArchClient`.
- Produces:
  - `OpenArchClient.ensure_mixin(doc_id: str, mixin: str) -> None` (`ensure_has_embeddings_mixin` delegates to it)
  - `class FieldsService(settings)` with
    - `async def vocabulary(self, client: OpenArchClient) -> dict[str, list[str]]`
    - `async def classify(self, markdown: str, vocabulary: dict[str, list[str]]) -> ClassifiedFields`
    - `async def store(self, client: OpenArchClient, doc_id: str, result: ClassifiedFields) -> None`
  - Setting `extract_model: str = "llama3.2:3b"`

- [ ] **Step 1: Write failing tests:**

```python
async def test_vocabulary_queries_as_caller_and_returns_names_only(): ...
    # respx /api/query returns docs with cinctx_contextProperties incl. values;
    # assert request Authorization is the caller's; result == {"invoice": ["total", "vendor_name"]}
    # and no value strings appear in the result

async def test_classify_sends_first_6000_chars_vocab_and_json_mode(): ...
    # inspect payload: model == "llama3.2:3b", response_format json_object,
    # user content contains markdown[:6000] and not markdown[6000:], contains "invoice: total, vendor_name"

async def test_store_adds_mixin_once_and_writes_properties(): ...
    # GET doc mixins ["SysHasEmbeddings"]; PUT 1 sets mixins [..., "CinContext"];
    # PUT 2 body == {"cinctx_contextProperties": {"document_type": "invoice", "total": 1.0},
    #               "cinctx_contextPropertyNames": ["document_type", "total"]}
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Vocabulary HXQL: `SELECT * FROM SysContent WHERE sys_mixinTypes = 'CinContext' ORDER BY sys_modified DESC`, `limit 200`. Prompt (system): choose an existing type when one fits, else a short new type name; reuse existing field names when meaning matches; only values present in the text; reply `{"type": ..., "fields": {...}}`. Timeout 300 s.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): field extraction service writes CinContext`.

### Task 9: `classified` enrichment stage

**Files:**
- Modify: `api/app/enrichment.py`, `api/app/main.py`
- Test: `api/tests/test_enrichment.py`

**Interfaces:**
- Consumes: `FieldsService`.
- Produces: `STAGES` ends with `"classified"`; `EnrichmentService.__init__(..., fields: FieldsService | None = None)`; stage detail `"{document_type} · {n} fields"`; failure details `"model returned invalid JSON"` or `"no write permission on this document"`.

- [ ] **Step 1: Write failing tests:**

```python
async def test_classified_stage_records_type_and_count(): ...
async def test_classification_failure_keeps_job_complete(): ...      # model 500 → stage failed, job.state == "complete"
async def test_no_write_permission_message(): ...                    # PUT 403 → detail == "no write permission on this document"
async def test_without_fields_service_stage_is_skipped(): ...        # fields=None → stage status "done", detail "skipped"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** after `indexed`, before graph; wire `FieldsService(settings)` in `create_app`.
- [ ] **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `feat(api): classify and extract fields during enrichment`.

### Task 10: Extracted fields in the UI

**Files:**
- Modify: `api/app/library.py` (`summarize` adds `"documentType"`), `web/src/types.ts`, `web/src/pages/DocumentPage.tsx`, `web/src/components/DocumentRow.tsx`, `web/src/pages/SearchPage.tsx`, `web/src/styles.css`, `web/src/components/EnrichmentStatus.tsx`
- Test: `api/tests/test_library.py`, `web/tests/library.test.tsx`, new `web/tests/document.test.tsx`

**Interfaces:**
- Produces: `summarize(doc)["documentType"]` = `cinctx_contextProperties.document_type` or `None`; `ExtractedFields({ properties, baselineMode })` component inside `DocumentPage` metadata tab; `DocumentRow` type chip.

- [ ] **Step 1: Write failing tests:** api `test_summarize_exposes_document_type`; web: panel shows badge "invoice", row `vendor_name` / `ACME`, label "AI-extracted · Studio + model"; panel absent when `baselineMode`; library row shows chip "invoice".
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Read-only table, keys displayed as-is. `EnrichmentStatus` owner map: `classified → "Studio + model"`. If Task 6 recorded `FIELD_QUERY`, add it as an HXQL example on `SearchPage`.
- [ ] **Step 4: Run** `npm test -- --run`, `npm run build`, api suite → PASS.
- [ ] **Step 5: Commit** `feat(web): extracted fields panel and type chips`.

### Task 11: Phase 2 capabilities, docs, live check

**Files:**
- Modify: `api/app/capabilities.py`, `api/tests/test_capabilities.py`, `README.md`, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `.env.example`

- [ ] **Step 1: Test + implement** new extension `("Document classification & field extraction", "Studio + model", "Typed fields written to OpenArch CinContext.", "fields.py")`; native "Metadata & content models" evidence mentions `CinContext`.
- [ ] **Step 2: Docs.** README: Phase 2 feature + `STUDIO_EXTRACT_MODEL` + `ollama pull llama3.2:3b`; deep dive: classified stage, vocabulary as caller, CinContext storage, Task 6 findings; GLOSSARY: *Document type*, *Extracted fields*.
- [ ] **Step 3: Live check.** Upload 3 sample invoices in different languages + one non-invoice; confirm type chips, fields panel, and (if available) the `FIELD_QUERY` HXQL search. Record in the ledger.
- [ ] **Step 4: Commit** `docs: Phase 2 — extracted fields`; ask the user before `git push`.

---

## Phase 3 — Reranking and model roles

### Task 12: Reranker service check

**Files:**
- Modify: `compose.yaml`, `.env.example`

- [ ] **Step 1:** Add service `reranker` (`image: ${STUDIO_RERANKER_IMAGE:-ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9}`, `command: --model-id ${STUDIO_RERANK_MODEL:-BAAI/bge-reranker-v2-m3}`, volume `reranker-models:/data`, no published port).
- [ ] **Step 2:** `docker compose up -d reranker`; from `studio-api`, `POST http://reranker:80/rerank` `{"query":"invoice total","texts":["The total is 10","Weather is nice"]}`. Expected: index 0 scores higher. If the model fails to load, switch the default to `BAAI/bge-reranker-base` and re-run.
- [ ] **Step 3: Commit** `chore: reranker service`.

### Task 13: Reranker seam

**Files:**
- Create: `api/app/rerank.py`
- Modify: `api/app/config.py`
- Test: `api/tests/test_rerank.py`

**Interfaces:**
- Produces:
  - Settings `reranker_url: str = ""` (Compose sets `http://reranker:80`), `rerank_model: str = "BAAI/bge-reranker-v2-m3"`
  - `@dataclass RerankOutcome(order: list[int], scores: list[float | None], status: str)` — `status` is `"reranked"` or `"skipped (<reason>)"`
  - `class Reranker(settings)` with `async def rerank(self, query: str, texts: list[str]) -> RerankOutcome`

- [ ] **Step 1: Write failing tests:**

```python
async def test_reorders_by_score(): ...                 # response [{"index":1,"score":0.9},{"index":0,"score":0.1}] → order [1,0]
async def test_unset_url_skips(): ...                   # status == "skipped (not configured)", order == [0,1,2]
async def test_timeout_skips(): ...                     # status == "skipped (timeout)"
async def test_5xx_skips(): ...                         # status == "skipped (HTTP 503)"
async def test_missing_index_falls_back(): ...          # 2 of 3 indexes returned → vector order, status "skipped (incomplete response)"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with a 3 s httpx timeout; `scores[i]` aligned to input index.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): reranker client with vector-order fallback`.

### Task 14: Rerank search and chat retrieval

**Files:**
- Modify: `api/app/agent.py`, `api/app/search.py`, `api/app/chat.py`, `api/app/main.py`, `web/src/types.ts`, `web/src/pages/SearchPage.tsx`, `web/src/components/RetrievalTrace.tsx`, `web/src/pages/AskPage.tsx`
- Test: `api/tests/test_agent.py`, `api/tests/test_search.py`, `web/tests/ask.test.tsx`

**Interfaces:**
- Consumes: `Reranker`, `RerankOutcome`.
- Produces: `Evidence.vector_score: float | None`; `AgentService(settings, enrichment, reranker=None)`; `AgentService.retrieve` returns `(evidence, rerank_status)`; chat `TOOL_CALL_END.result.rerank = status`; search `provenance.rerank = status`; each search result gains `vectorScore`; `RetrievalTrace({ count, rerank })`.

- [ ] **Step 1: Write failing tests:**

```python
async def test_retrieve_overfetches_reranks_and_truncates(): ...
    # top_k=2 → semantic_search called with limit 6; reranker reverses; evidence ids reversed, len 2,
    # score == rerank score, vector_score == original
async def test_semantic_search_reports_rerank_status(): ...   # provenance["rerank"] == "reranked"
async def test_reranker_down_keeps_vector_order(): ...        # provenance["rerank"].startswith("skipped")
async def test_baseline_mode_rerank_not_reached(): ...        # baseline client → /api/search 403 (existing gate) — assert reranker route not called
```

Web: `RetrievalTrace` renders "Reranked" or the skip reason; SearchPage trace shows `rerank`.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Candidates `min(top_k * 3, 30)`; keyword mode reranks after the term filter.
- [ ] **Step 4: Run** api + web suites, `npm run build` → PASS.
- [ ] **Step 5: Commit** `feat: rerank search and chat retrieval`.

### Task 15: Model roles and warm-up

**Files:**
- Modify: `api/app/config.py`, `api/app/graph.py`, `api/app/main.py`, `studio-issues/01-graph-auto-extraction-reliability.md`, `studio-issues/02-default-chat-model-too-heavy.md`
- Create: `api/app/warmup.py`
- Test: `api/tests/test_config.py` (new), `api/tests/test_warmup.py` (new), `api/tests/test_graph.py`

**Interfaces:**
- Produces: `extract_model` accepts env `STUDIO_EXTRACT_MODEL` or deprecated `STUDIO_GRAPH_MODEL` (`validation_alias=AliasChoices(...)`); `graph_model` field removed; `chat_model` default `"llama3.2:3b"`; `async def warm_up(settings: Settings) -> None`; `create_app` registers a lifespan that schedules `warm_up` with `asyncio.create_task` (not awaited).

- [ ] **Step 1: Write failing tests:**

```python
def test_graph_model_env_is_alias_for_extract_model(monkeypatch):
    monkeypatch.setenv("STUDIO_GRAPH_MODEL", "tiny")
    assert Settings().extract_model == "tiny"

def test_chat_default_is_light():
    assert Settings().chat_model == "llama3.2:3b"

async def test_warm_up_pings_extract_and_chat_and_swallows_errors(): ...  # both routes called; one 500 → no raise
async def test_graph_uses_extract_model(): ...                             # payload model == settings.extract_model
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Warm-up sends one `chat/completions` with `max_tokens: 1` per distinct model, 120 s timeout, logs failures. Mark both studio-issues as resolved with a "Resolution" section naming the change.
- [ ] **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `feat(api): model roles and startup warm-up`.

### Task 16: Phase 3 capabilities, docs, GitHub About, live check

**Files:**
- Modify: `api/app/capabilities.py`, `api/tests/test_capabilities.py`, `README.md`, `NOTICE`, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `.env.example`, `AGENTS.md`

- [ ] **Step 1: Test + implement** extension `("Reranking", "Studio + model", "Cross-encoder reorders permitted candidates.", "rerank.py")` and runtime `{"name": "text-embeddings-inference", "role": "Reranking"}`.
- [ ] **Step 2: Verify licenses** for text-embeddings-inference and the chosen reranker model card; add to NOTICE + README table.
- [ ] **Step 3: Docs.** README: model-role table, `STUDIO_RERANKER_IMAGE` per architecture, `STUDIO_RERANKER_URL`, `STUDIO_RERANK_MODEL`, `STUDIO_EXTRACT_MODEL` (and the deprecated alias); deep dive: reranking + roles + warm-up; GLOSSARY: *Rerank*, *Model role*; AGENTS.md `api/` line lists `rerank.py`, `fields.py`.
- [ ] **Step 4: GitHub About.** Draft description (≤ 120 chars) and topics; show the exact text to the user; after approval run `gh repo edit haaldinger/openarch-studio --description "<text>" --add-topic <t> ...`.
- [ ] **Step 5: Live check.** Cold-start the stack; Graph tab populated for a freshly enriched doc (issue 01); Ask answers on CPU in reasonable time with `llama3.2:3b` (issue 02); Search trace shows "reranked"; stop `reranker` and confirm "skipped". Record in the ledger.
- [ ] **Step 6: Commit** `docs: Phase 3 — reranking, model roles`; ask the user before `git push`.
