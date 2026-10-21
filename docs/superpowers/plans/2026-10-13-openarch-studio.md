# OpenArch Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first OpenArch showcase that uploads and enriches documents, exposes native capabilities clearly, and answers permission-aware questions with citations.

**Architecture:** A React/Vite SPA talks only to a same-origin FastAPI BFF. The BFF keeps memory-only OpenArch sessions, orchestrates Tika and an OpenAI-compatible model endpoint, writes OpenArch-compatible `SysEmbeddings` Parquet documents, and performs retrieval as the signed-in user. Docker Compose adds Studio, Tika, and Ollama without changing OpenArch's Java reactor.

**Tech Stack:** React, TypeScript, Vite, React Router, Lucide, plain CSS, FastAPI, Pydantic, HTTPX, PyArrow, pytest, Vitest, Testing Library, Playwright, nginx, Apache Tika, Ollama, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-13-openarch-studio-design.md`

## Global Constraints

- Keep all product code under `pocs/openarch-studio/`; do not modify OpenArch Java modules.
- OpenArch remains the system of record for binaries, metadata, ACLs, and `SysEmbeddings`.
- Every OpenArch retrieval request uses the signed-in user's Basic credentials.
- Credentials exist only in the API process memory and an opaque HTTP-only, SameSite session cookie identifies the session.
- The model API is OpenAI-compatible; Ollama is the default but the base URL and model names are configurable.
- Pad every embedding and semantic query vector with zeros to exactly 1024 values; reject vectors longer than 1024.
- Label OpenArch-native and Studio-added capabilities explicitly in product copy and response metadata.
- Supported first-release files are PDF, DOCX, TXT, Markdown, and HTML.
- Target WCAG 2.2 AA and retain critical workflows on desktop and mobile.
- Active job history is memory-backed; durable readiness is reconstructed from OpenArch documents and `SysEmbeddings` children.
- This workspace snapshot has no `.git`; execute commit steps only in a real clone or after version control is initialized.

## Review Focus

- A supported extension with a misleading or missing MIME type: `test_mime_mismatch_preserves_document` validates Tika's detected type and fails extraction without deleting the OpenArch document.
- OpenArch authentication versus outage: `test_openarch_401_invalidates_session_and_outage_returns_503` invalidates on 401 but retains the session and returns 503 on transport failure.
- Invalid provider vectors: `test_embedding_dimension_invalid_before_write` rejects zero, more than 1024, or inconsistent lengths before any `SysEmbeddings` child is written.
- Access revoked after retrieval: `test_revoked_citation_does_not_leak` returns 403/404 without returning cached chunk text.
- Streaming cancellation: `test_chat_disconnect_closes_upstream` closes the model stream while retaining submitted question and retrieval metadata in the browser.

---

## File Structure

```text
pocs/openarch-studio/
  compose.yaml                 # Includes the root OpenArch stack and adds Studio, Tika, Ollama
  .env.example                 # Configurable URLs and model names
  README.md                    # Local run instructions and native/extension ledger
  api/
    Dockerfile
    pyproject.toml
    app/
      __init__.py
      main.py                  # FastAPI construction and router registration
      config.py                # Pydantic settings
      models.py                # Shared API/domain models
      auth.py                  # Memory session store and auth dependency
      openarch.py              # Typed OpenArch HTTP client
      enrichment.py            # Extraction, chunking, job state, orchestration
      parquet.py               # 1024-vector normalization and embedding Parquet writer
      agent.py                 # Retrieval, prompt grounding, SSE chat stream
      routes.py                # Thin HTTP endpoints
    tests/
      conftest.py
      test_auth.py
      test_openarch.py
      test_library.py
      test_parquet.py
      test_enrichment.py
      test_search.py
      test_agent.py
      test_capabilities.py
  web/
    Dockerfile
    nginx.conf
    package.json
    vite.config.ts
    playwright.config.ts
    src/
      main.tsx
      app.tsx                  # Router and authenticated shell
      api.ts                   # Fetch and SSE client
      types.ts                 # API response contracts
      styles.css               # Tokens, responsive layout, states, motion
      pages/
        LoginPage.tsx
        LibraryPage.tsx
        SearchPage.tsx
        AskPage.tsx
        DocumentPage.tsx
        ActivityPage.tsx
        CapabilityPage.tsx
      components/
        AppShell.tsx
        DocumentRow.tsx
        EnrichmentStatus.tsx
        CitationList.tsx
        RetrievalTrace.tsx
    tests/
      app.test.tsx
      library.test.tsx
      ask.test.tsx
      capability.test.tsx
    e2e/
      studio.spec.ts
```

### Task 1: Runnable Companion Stack And Product Shell

**Files:**
- Create: `pocs/openarch-studio/compose.yaml`
- Create: `pocs/openarch-studio/.env.example`
- Create: `pocs/openarch-studio/api/{Dockerfile,pyproject.toml,app/__init__.py,app/config.py,app/main.py}`
- Create: `pocs/openarch-studio/web/{Dockerfile,nginx.conf,package.json,vite.config.ts,src/main.tsx,src/app.tsx,src/styles.css}`
- Create: `pocs/openarch-studio/web/src/pages/{LoginPage.tsx,LibraryPage.tsx,SearchPage.tsx,AskPage.tsx,DocumentPage.tsx,ActivityPage.tsx,CapabilityPage.tsx}`
- Create: `pocs/openarch-studio/web/src/components/AppShell.tsx`
- Test: `pocs/openarch-studio/api/tests/test_health.py`
- Test: `pocs/openarch-studio/web/tests/app.test.tsx`

**Interfaces:**
- Produces: `GET /api/health -> {status, openarch, tika, model}` and named React routes `/library`, `/search`, `/ask`, `/documents/:id`, `/activity`, `/capabilities`.

- [ ] **Step 1: Write failing API and UI shell tests**

Assert `/api/health` reports component states without requiring auth. Assert the SPA renders the seven routes, navigation labels, and mobile navigation without marketing-page content.

- [ ] **Step 2: Run the tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_health.py -v`

Run: `cd pocs/openarch-studio/web && npm test -- --run tests/app.test.tsx`

Expected: FAIL because the applications and routes do not exist.

- [ ] **Step 3: Implement the minimal runnable stack and visual shell**

`Settings` must expose `openarch_url`, `tika_url`, `model_base_url`, `embedding_model`, `chat_model`, and `session_ttl_seconds`. Compose includes `../../docker-compose.yml`; nginx serves the SPA and proxies `/api/` to `studio-api`. Build the approved light editorial visual direction with CSS variables, responsive constraints, visible focus, reduced motion, and Lucide icons.

- [ ] **Step 4: Run unit and Compose validation**

Run the two Step 2 commands, then `docker compose -f pocs/openarch-studio/compose.yaml config --quiet`.

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: scaffold OpenArch Studio companion stack"
```

### Task 2: Session Boundary And Typed OpenArch Client

**Files:**
- Create: `pocs/openarch-studio/api/app/{models.py,auth.py,openarch.py,routes.py}`
- Create: `pocs/openarch-studio/api/tests/{conftest.py,test_auth.py,test_openarch.py}`
- Create: `pocs/openarch-studio/web/src/{api.ts,types.ts}`
- Modify: `pocs/openarch-studio/api/app/main.py`
- Modify: `pocs/openarch-studio/web/src/{app.tsx,pages/LoginPage.tsx}`

**Interfaces:**
- Produces: `Credentials(username: str, password: SecretStr)`, `SessionStore.create/get/delete`, `current_credentials(request)`, and `OpenArchClient` methods `get_document`, `query`, `upload`, `update_document`, `download`, `semantic_search`.
- Produces: `POST/GET/DELETE /api/session` and browser helpers `login`, `logout`, `getSession`, `apiFetch`.

- [ ] **Step 1: Write failing session and client tests**

Cover successful login against the OpenArch root document, invalid credentials, opaque HTTP-only SameSite cookie, TTL expiration, logout, and `test_openarch_401_invalidates_session_and_outage_returns_503`. Verify authorization headers never appear in logs or API responses.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_auth.py tests/test_openarch.py -v`

Expected: FAIL because auth and client modules do not exist.

- [ ] **Step 3: Implement memory sessions and the typed HTTPX client**

Use an opaque `secrets.token_urlsafe(32)` session ID. Validate credentials with `GET /api/documents/00000000-0000-0000-0000-000000000000`. Map OpenArch 401 to session invalidation, 403 unchanged, 404 unchanged, and transport errors to 503.

- [ ] **Step 4: Implement authenticated routing in the SPA**

Login submits only to `/api/session`; no credentials enter local or session storage. Unauthenticated routes redirect to login and 401 responses clear client auth state.

- [ ] **Step 5: Run API and UI tests**

Run the Step 2 command and `cd pocs/openarch-studio/web && npm test -- --run tests/app.test.tsx`.

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pocs/openarch-studio/api pocs/openarch-studio/web
git commit -m "feat: add permission-preserving Studio sessions"
```

### Task 3: Library, Upload, And Document Inspection

**Files:**
- Modify: `pocs/openarch-studio/api/app/{models.py,openarch.py,routes.py}`
- Create: `pocs/openarch-studio/api/tests/test_library.py`
- Modify: `pocs/openarch-studio/web/src/{api.ts,types.ts,pages/LibraryPage.tsx,pages/DocumentPage.tsx,styles.css}`
- Create: `pocs/openarch-studio/web/src/components/DocumentRow.tsx`
- Create: `pocs/openarch-studio/web/tests/library.test.tsx`

**Interfaces:**
- Produces: `GET /api/documents`, `POST /api/documents` multipart, `GET /api/documents/{doc_id}`, and `GET /api/documents/{doc_id}/content`.
- Extends `OpenArchClient` with `create_file`, `attach_upload`, and `get_effective_acl`.

- [ ] **Step 1: Write failing API tests for browse, upload, and inspection**

Assert root browsing uses `/api/query`, upload creates `SysFile`, streams the binary to `/api/upload`, attaches `sysfile_blob`, and returns the OpenArch document. Cover unsupported extension, misleading MIME type retained for later Tika validation, empty file, OpenArch partial failure cleanup of only the temporary upload, and permission errors.

- [ ] **Step 2: Run API tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_library.py -v`

Expected: FAIL with missing routes/client methods.

- [ ] **Step 3: Implement the library endpoints**

Limit accepted extensions to `.pdf`, `.docx`, `.txt`, `.md`, `.html`, and `.htm`. Never buffer the source twice. Preserve the OpenArch document if binary attachment succeeds, even when later enrichment fails.

- [ ] **Step 4: Write and run failing UI tests**

Assert the library lists folders/files, accepts drag/drop and file picker upload, shows immediate progress, opens document metadata/raw JSON/ACL/content tabs, and remains usable at a 390px viewport.

Run: `cd pocs/openarch-studio/web && npm test -- --run tests/library.test.tsx`

Expected: FAIL before UI implementation.

- [ ] **Step 5: Implement Library and Document Inspector baseline**

Use unframed list/detail layouts rather than nested cards. Keep technical JSON behind progressive disclosure. Show an explicit `OpenArch native` label on stored binary, metadata, and ACL sections.

- [ ] **Step 6: Run API and UI tests**

Run both Step 2 and Step 4 commands.

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: add OpenArch document workspace"
```

### Task 4: Enrichment Pipeline And Activity

**Files:**
- Create: `pocs/openarch-studio/api/app/{parquet.py,enrichment.py}`
- Create: `pocs/openarch-studio/api/tests/{test_parquet.py,test_enrichment.py}`
- Modify: `pocs/openarch-studio/api/app/{models.py,openarch.py,routes.py}`
- Modify: `pocs/openarch-studio/web/src/{api.ts,types.ts,pages/LibraryPage.tsx,pages/DocumentPage.tsx,pages/ActivityPage.tsx,styles.css}`
- Create: `pocs/openarch-studio/web/src/components/EnrichmentStatus.tsx`

**Interfaces:**
- Produces: `normalize_vector(vector: Sequence[float]) -> list[float]`, `write_embeddings(chunks: Sequence[EmbeddedChunk]) -> bytes`, `chunk_text(text: str) -> list[Chunk]`, `EnrichmentService.start/retry/status/list_jobs`.
- Produces: `POST /api/documents/{doc_id}/enrich`, `POST /api/jobs/{job_id}/retry`, and `GET /api/jobs`.

- [ ] **Step 1: Write failing vector and Parquet contract tests**

Assert vectors shorter than 1024 are zero-padded, exactly 1024 values are unchanged, and `test_embedding_dimension_invalid_before_write` rejects longer, empty, or inconsistent vectors before writing. Assert IDs are UUIDs and PyArrow output exactly matches OpenArch fields `id`, `type`, `vector`, `text`, nullable `blobref`, and nullable location variants.

- [ ] **Step 2: Run contract tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_parquet.py -v`

Expected: FAIL because the writer does not exist.

- [ ] **Step 3: Implement vector normalization and Parquet writing**

Keep the schema local to Studio but test it against `modules/platform/openarch-opensearch/src/test/resources/schemas/embedding.avsc`. Embedding type is `<provider>/<model>/<model-version>` and must remain under OpenArch's 256-character limit.

- [ ] **Step 4: Write failing enrichment orchestration tests**

Cover Tika extraction, deterministic chunk IDs, model embedding calls, `SysHasEmbeddings` update, Parquet upload, `SysEmbeddings` child creation, index wait, stage-specific failure, retry, cancellation, `test_mime_mismatch_preserves_document`, and reconstruction of durable readiness after restart. Add `test_upload_auto_enriches_to_searchable_output`, which submits a file through `POST /api/documents`, observes every stage, and verifies the resulting chunk through semantic search.

- [ ] **Step 5: Implement enrichment orchestration**

Use FastAPI background tasks and an in-memory job store. A successful `POST /api/documents` automatically starts enrichment. POST source bytes to Tika, chunk by paragraphs with bounded overlap, call the OpenAI-compatible embeddings endpoint, upload Parquet, and create the `_e_<embedding-type>` child. Do not add Celery, Redis, or a second vector database.

- [ ] **Step 6: Implement Activity and readiness UI**

Show stored, extracted, chunked, embedded, indexed stages with ownership labels (`OpenArch`, `Studio + Tika`, `Studio + model`). Errors retain the source document and expose retry at the failed stage.

- [ ] **Step 7: Run focused tests**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_parquet.py tests/test_enrichment.py -v`

Run: `cd pocs/openarch-studio/web && npm test -- --run tests/library.test.tsx`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: enrich documents into OpenArch embeddings"
```

### Task 5: Keyword, HXQL, And Semantic Search

**Files:**
- Modify: `pocs/openarch-studio/api/app/{models.py,openarch.py,routes.py}`
- Create: `pocs/openarch-studio/api/tests/test_search.py`
- Modify: `pocs/openarch-studio/web/src/{api.ts,types.ts,pages/SearchPage.tsx,styles.css}`

**Interfaces:**
- Produces: `POST /api/search` accepting `{mode: keyword|hxql|semantic, query, limit}` and returning normalized documents or embedding hits plus `provenance`.

- [ ] **Step 1: Write failing search tests**

Assert keyword/HXQL calls `/api/query`; semantic generates an embedding, normalizes it to 1024, and calls `/api/query/embeddings`. Cover empty queries, malformed HXQL, model unavailability, OpenArch 403, pagination, no results, and `test_semantic_search_excludes_unauthorized_results`, proving different credentials return different hits.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_search.py -v`

Expected: FAIL because `/api/search` does not exist.

- [ ] **Step 3: Implement normalized search responses**

Return provenance fields `providedBy`, `extendedBy`, `embeddingType`, `requestPath`, and timing without returning vectors or credentials.

- [ ] **Step 4: Implement the Search page**

Use a segmented mode control, query field, result list, score/source metadata, pagination, and an expandable request/provenance trace. Do not expose raw HXQL in keyword mode.

- [ ] **Step 5: Run search and frontend tests**

Run the Step 2 command and `cd pocs/openarch-studio/web && npm test -- --run`.

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: add attributed OpenArch search modes"
```

### Task 6: Permission-Aware Agent Chat With Citations

**Files:**
- Create: `pocs/openarch-studio/api/app/agent.py`
- Create: `pocs/openarch-studio/api/tests/test_agent.py`
- Modify: `pocs/openarch-studio/api/app/{models.py,routes.py}`
- Modify: `pocs/openarch-studio/web/src/{api.ts,types.ts,pages/AskPage.tsx,styles.css}`
- Create: `pocs/openarch-studio/web/src/components/{CitationList.tsx,RetrievalTrace.tsx}`
- Create: `pocs/openarch-studio/web/tests/ask.test.tsx`

**Interfaces:**
- Produces: `AgentService.retrieve(question, credentials) -> EvidenceSet`, `AgentService.stream_answer(question, history, evidence) -> AsyncIterator[AgentEvent]`, and `POST /api/chat` as SSE events `retrieval`, `token`, `citations`, `done`, `error`.

- [ ] **Step 1: Write failing agent tests**

Assert retrieval calls OpenArch with current credentials, semantic and exact-term evidence merge deterministically, no-evidence questions return an insufficiency answer, prompt content is bounded, and citations match supplied evidence. Add `test_revoked_citation_does_not_leak` and `test_chat_disconnect_closes_upstream`; model errors must preserve retrieval metadata.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_agent.py -v`

Expected: FAIL because `AgentService` does not exist.

- [ ] **Step 3: Implement bounded retrieval and streaming generation**

The model receives an instruction that evidence is untrusted data and every factual claim must cite provided chunk IDs. Reject model-emitted citation IDs absent from `EvidenceSet`. Keep conversation history in the browser request; do not add a conversation database.

- [ ] **Step 4: Write failing Ask page tests**

Assert streaming tokens, pending state, inline citation markers, source preview, retrieval trace, retry after generation failure, insufficient-evidence copy, keyboard submission, and retained question/citations after interruption.

- [ ] **Step 5: Implement Ask page and citation navigation**

Citations route to `/documents/:id?chunk=<chunk-id>`. Retrieval trace shows `Studio agent -> OpenArch retrieval -> permitted chunks -> configured model` and labels which component owns each step.

- [ ] **Step 6: Run agent and UI tests**

Run Step 2 and `cd pocs/openarch-studio/web && npm test -- --run tests/ask.test.tsx`.

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: add cited permission-aware agent chat"
```

### Task 7: Capability Map And Complete Inspector

**Files:**
- Create: `pocs/openarch-studio/api/tests/test_capabilities.py`
- Modify: `pocs/openarch-studio/api/app/routes.py`
- Modify: `pocs/openarch-studio/web/src/{types.ts,pages/CapabilityPage.tsx,pages/DocumentPage.tsx,styles.css}`
- Create: `pocs/openarch-studio/web/tests/capability.test.tsx`

**Interfaces:**
- Produces: `GET /api/capabilities -> {native[], extensions[], provenanceFlow[], runtimes[]}` matching the approved ledger.

- [ ] **Step 1: Write failing ledger tests**

Assert every capability has `name`, `owner`, `description`, and `evidence`; `test_capability_ownership_is_unambiguous` proves OpenArch native entries cannot name Tika/Ollama/Studio as owner and extensions cannot claim native status. Runtime health is separate from capability ownership, and users/groups/vocabularies are marked native but not surfaced as v1 administration workflows.

- [ ] **Step 2: Run tests and verify failure**

Run: `cd pocs/openarch-studio/api && uv run pytest tests/test_capabilities.py -v`

Expected: FAIL because the endpoint does not exist.

- [ ] **Step 3: Implement the capability endpoint and page**

Render the two-column native-versus-extension ledger, active runtime state, and provenance flow. Complete Document Inspector tabs for metadata, effective ACL, extracted chunks, embedding identity, raw OpenArch JSON, and preview/download.

- [ ] **Step 4: Run API and UI tests**

Run Step 2 and `cd pocs/openarch-studio/web && npm test -- --run tests/capability.test.tsx`.

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pocs/openarch-studio
git commit -m "feat: expose OpenArch capability provenance"
```

### Task 8: End-To-End Verification And Local Run Guide

**Files:**
- Create: `pocs/openarch-studio/web/playwright.config.ts`
- Create: `pocs/openarch-studio/web/e2e/studio.spec.ts`
- Create: `pocs/openarch-studio/README.md`
- Modify: `pocs/openarch-studio/compose.yaml`

**Interfaces:**
- Consumes: all prior API and UI contracts.
- Produces: one documented command path and executable acceptance workflow.

- [ ] **Step 1: Add deterministic E2E fixtures and mocked model mode**

Configure a test-only OpenAI-compatible fixture server or HTTP route that returns fixed embeddings and streamed answers. Do not make Playwright depend on model quality or network downloads.

- [ ] **Step 2: Write the failing acceptance workflow**

Test admin login, PDF upload, stage progression, document inspection, semantic search, cited chat answer, citation navigation, capability attribution, logout, and a second-user permission denial. Add desktop and 390px mobile screenshot assertions and reduced-motion coverage.

- [ ] **Step 3: Run Playwright and verify failure**

Run: `cd pocs/openarch-studio/web && npx playwright test`

Expected: FAIL until fixture wiring and any integration gaps are complete.

- [ ] **Step 4: Finish Compose health checks and run instructions**

Document model pulls, `.env` values, startup, login fixtures, supported files, native-versus-extension ledger, known POC limits, and teardown. Add health checks for Studio API, Tika, Ollama, and OpenArch dependencies.

- [ ] **Step 5: Run the complete verification suite**

Run: `cd pocs/openarch-studio/api && uv run pytest -v`

Run: `cd pocs/openarch-studio/web && npm test -- --run && npm run build && npx playwright test`

Run: `docker compose -f pocs/openarch-studio/compose.yaml config --quiet`

Expected: all pass; screenshots contain rendered content without overlap or blank preview regions.

- [ ] **Step 6: Commit**

```bash
git add pocs/openarch-studio
git commit -m "test: verify OpenArch Studio workflow"
```
