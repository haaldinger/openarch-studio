# OpenArch Studio Design

## Purpose

OpenArch Studio is a self-contained proof-of-concept application that demonstrates how OpenArch can serve as the permission-aware system of record for AI-ready unstructured content.

The first release supports one complete demonstration:

1. Sign in as an OpenArch user.
2. Upload a document.
3. Enrich it through extraction, chunking, and embedding generation.
4. Inspect the document, metadata, permissions, chunks, and embeddings.
5. Retrieve it through keyword, advanced, or semantic search.
6. Ask questions whose answers are grounded in permitted OpenArch content.
7. Open and verify every cited source.

The primary audience is a balanced mix of technical evaluators, architects, business stakeholders, and repository operators. The interface must work as a real content workspace while making the underlying architecture inspectable on demand.

## Product Boundary

Studio is a companion stack under `pocs/openarch-studio/`. It does not modify OpenArch's Java modules or join the Maven reactor.

The stack contains:

- A React and Vite single-page application.
- A FastAPI backend-for-frontend and enrichment service.
- Apache Tika for document text and metadata extraction.
- Ollama for local embeddings and chat generation.
- An OpenAI-compatible model adapter so another provider can be configured without application changes.
- The existing OpenArch, MongoDB, and OpenSearch services.
- An nginx entrypoint that serves the UI and proxies the Studio and OpenArch APIs through one origin.

The first release uses FastAPI background tasks for enrichment. A distributed task queue is not justified for a single-node POC and can be added when jobs must survive process restarts or run across workers.

Active job progress and recent job history are memory-backed in the POC and reset when Studio restarts. Durable readiness is reconstructed from the source document, its metadata, and its `SysEmbeddings` children in OpenArch.

## Capability Attribution

Studio must clearly distinguish OpenArch capabilities from extensions. The distinction appears in a dedicated Capability Map and in contextual provenance details throughout the application.

| OpenArch native capability | Studio or open-source extension |
| --- | --- |
| Document and binary storage | Visual content workspace |
| Metadata and content models | Metadata and schema inspector |
| ACLs and effective permissions | Permission visualization |
| Keyword and advanced HXQL queries | Guided search interface |
| `SysEmbeddings` storage and vector search | Tika extraction, chunking, Parquet generation, and embedding orchestration |
| Users, groups, and vocabularies | Capability discovery and API evidence; administration UI is deferred |
| REST and OpenAPI contract | Same-origin session gateway |
| Permission-aware retrieval | RAG orchestration and streaming agent chat |
| OpenSearch indexing | Citations and retrieval trace |
| Docker deployment | Integrated POC Compose stack |

Studio must not describe extraction, embedding generation, language-model inference, enrichment orchestration, or chat as native OpenArch features.

Each chat response exposes this provenance chain:

`Question -> Studio agent -> OpenArch retrieval -> permitted chunks -> configured model -> cited answer`

## Authentication And Authorization

OpenArch remains the authority for identity and content authorization.

The user signs in through Studio with OpenArch credentials. Studio validates them against an authenticated OpenArch endpoint and creates a random, HTTP-only, SameSite session cookie. Credentials are retained only in server memory for the session and are never written to browser storage, logs, files, or databases. Restarting Studio invalidates all sessions.

Every OpenArch request made for browsing, searching, retrieval, or citation resolution uses the signed-in user's credentials. The agent cannot elevate identity or use a service account for retrieval. This preserves OpenArch ACL behavior throughout the workflow.

The POC must document that memory-backed Basic Auth sessions are not a production identity design. OIDC, distributed sessions, secret encryption at rest, and production ingress controls remain future work.

## Content And Enrichment Flow

The initial supported formats are PDF, DOCX, TXT, Markdown, and HTML.

Upload and enrichment proceed as follows:

1. Studio creates a `SysFile` document in OpenArch.
2. Studio uploads the original binary through `/api/upload` and attaches it through `sysfile_blob`.
3. Tika extracts normalized text and metadata from the binary.
4. Studio chunks the text with deterministic chunk identifiers and source locations.
5. The configured embedding model generates one vector per chunk.
6. Studio ensures the source document has the `SysHasEmbeddings` mixin.
7. Studio writes chunk identifiers, text, vectors, and source locations using OpenArch's expected Parquet schema.
8. Studio uploads the Parquet binary and creates a `SysEmbeddings` child document beneath the source document.
9. Studio waits for OpenSearch indexing before marking the document ready for semantic retrieval.

The original file remains stored when extraction or embedding fails. Each stage records state, timing, and a concise error. Failed stages can be retried without recreating the source document.

Embedding type includes the model identity and version so vectors from incompatible models are never mixed in one semantic query.

## Agent And Retrieval

The first agent is deliberately bounded. It has explicit tools for:

- OpenArch semantic search through `/api/query/embeddings`.
- OpenArch keyword or HXQL search through `/api/query`.
- Reading a permitted OpenArch document and resolving a cited chunk.

For each question, the agent:

1. Generates a query embedding.
2. Runs semantic retrieval as the signed-in user.
3. Runs keyword retrieval when it can improve exact-name, identifier, or phrase matching.
4. Merges and ranks evidence without bypassing OpenArch permissions.
5. Sends only retrieved evidence to the configured chat model.
6. Streams an answer and structured citations to the browser.
7. States that the available evidence is insufficient when retrieved context cannot support an answer.

A citation includes the OpenArch document ID, title, chunk ID, source location when available, and retrieval score. Selecting a citation opens the document inspector at the relevant chunk. The retrieval trace exposes tool calls, timings, search mode, and result counts without exposing credentials or vectors.

The model adapter targets an OpenAI-compatible API. Ollama is the default local runtime; operators may configure another compatible base URL and model names.

## User Experience

The application opens directly into the workspace after authentication. It is not a marketing landing page.

### Library

Library provides repository browsing, document upload, type and readiness filters, and compact enrichment status. Upload immediately creates a visible document row whose stages progress from stored to extracted, chunked, embedded, and indexed.

### Search

Search provides keyword, advanced HXQL, and semantic modes within one surface. Results show document identity, matching excerpts, retrieval score where applicable, and permission context. Technical request and response details are available through progressive disclosure.

### Ask

Ask provides streaming multi-turn chat over the permitted enriched corpus. Answers carry inline citation markers, a source list, and a collapsible retrieval trace. Opening a citation transitions to the document inspector without losing the conversation.

### Document Inspector

The inspector presents a document preview alongside metadata, effective permissions, extracted text, chunks, embedding information, and raw OpenArch JSON. It labels which values are stored by OpenArch and which were generated by Studio's enrichment pipeline.

### Activity

Activity displays enrichment jobs, current stages, durations, model/runtime health, errors, and retry controls.

### Capability Map

The Capability Map presents the native-versus-extension ledger from this specification and the active runtime components. It is available from the primary navigation so demonstrations can state provenance explicitly.

## Visual Direction

Studio uses a bold innovation-showcase direction with a light editorial canvas, strong typography, document-centered composition, and vivid functional colors. It avoids neon-on-dark AI styling, decorative gradients, excessive cards, and dashboard chrome.

Motion communicates enrichment progress, streamed answers, and navigation context. It respects reduced-motion preferences. Desktop and mobile retain all critical workflows, with touch targets and layouts adapted rather than hidden.

Accessibility targets WCAG 2.2 AA for contrast, keyboard navigation, focus handling, labels, status announcements, and reduced motion.

## Error Handling

- Authentication failures return to sign-in without browser-native Basic Auth prompts.
- OpenArch unavailability is distinguished from authorization failure.
- Upload, extraction, embedding, indexing, retrieval, and generation failures are shown as separate stages.
- A failed enrichment job never deletes or conceals the stored source document.
- Retry resumes from the earliest failed stage when existing outputs remain valid.
- Model unavailability disables enrichment and chat actions while leaving OpenArch browsing and non-semantic search usable.
- Chat generation failure preserves the question and retrieved citations so the user can retry.

## Testing And Acceptance Criteria

Automated coverage includes:

- Unit tests for the OpenArch client, session behavior, chunking, and provider adapters.
- Parquet schema tests against the `SysEmbeddings` shape used by OpenArch.
- Contract tests for OpenArch request and response handling.
- An integration test covering upload, binary attachment, extraction, embedding creation, indexing, and semantic retrieval.
- A permission test proving that two OpenArch users receive different retrieval evidence where ACLs differ.
- Deterministic agent tests using a mocked OpenAI-compatible endpoint.
- Citation tests proving each cited chunk resolves to a document accessible to the current user.
- Playwright workflows and screenshots for desktop and mobile.
- Canvas and media checks where document preview rendering uses canvas-based components.

The POC is accepted when a fresh Compose deployment can complete the full sign-in-to-cited-answer workflow using the documented local configuration, and the Capability Map accurately attributes every demonstrated feature.

## Deferred POCs

The following are intentionally outside the first release:

- Knowledge graph extraction and visualization.
- Ontology authoring and semantic classification.
- External repository connectors.
- User, group, and vocabulary administration workflows.
- Production identity and multi-instance session storage.
- Distributed enrichment workers and durable job queues.
- Automated evaluation suites for answer quality.

The next recommended POC adds a graph sidecar using open-source entity and relation extraction, an explicit ontology layer, and graph-enhanced retrieval while retaining OpenArch as the permission and source-document authority.
