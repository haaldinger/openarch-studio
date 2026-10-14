# OpenArch Studio

A self-contained proof-of-concept that shows **OpenArch as a complete, permission-aware
AI-ready content platform** — and makes explicit which capabilities are OpenArch's own and
which are added on top.

One workflow, end to end:

> **sign in → upload → enrich → inspect → search → ask → open citation**

Upload a document; Studio stores it in OpenArch, extracts text with Tika, chunks and embeds it
with a local model, and writes the vectors back as an OpenArch `SysEmbeddings` child. Then search
it three ways and ask an agent questions whose answers are grounded in — and cited from — only the
content you're allowed to read.

## What's OpenArch vs. what Studio adds

| OpenArch native | Studio / open-source extension |
|---|---|
| Document & binary storage, metadata, content models | Visual content workspace |
| ACLs & effective permissions | Permission visualization |
| Keyword & advanced HXQL queries | Guided search interface |
| `SysEmbeddings` storage & vector search | Tika extraction, chunking, embedding (Ollama) |
| Permission-aware retrieval (runs as the caller) | RAG orchestration & streaming cited chat |
| OpenSearch indexing | Citations & retrieval trace |
| REST / OpenAPI contract | Same-origin, memory-only session gateway |

The in-app **Capability map** (`/capabilities`) is the live version of this table. Studio never
labels Tika extraction, embedding, model inference, or chat as native OpenArch features.

## Architecture

```
Browser (React/Vite SPA)
      │  same-origin
      ▼
 nginx ──► Studio API (FastAPI BFF)
                 ├─► OpenArch   (documents, ACLs, SysEmbeddings, vector search)
                 ├─► Apache Tika (text + metadata extraction)
                 └─► Ollama      (OpenAI-compatible embeddings + chat)
```

- Credentials are held in **server memory only**, keyed by an HTTP-only cookie. A restart drops
  every session; nothing is written to the browser.
- Every OpenArch call is made as the signed-in user, so ACLs stay in force through search and chat.
- No OpenArch Java module is modified — this stack lives entirely under `pocs/openarch-studio/`.

## Run it (full stack)

Requires Docker. From this directory:

```bash
cp .env.example .env
export OPENARCH_VERSION=1.0.0        # the OpenArch base image tag
docker compose up -d --build

# one-time: pull the local models Ollama will serve
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.1

# open the UI
open http://localhost:8900
```

Sign in with an OpenArch user (the default dev store includes `admin` / `password`). Upload a PDF,
DOCX, TXT, Markdown, or HTML file, watch it enrich on the **Activity** page, then try **Search** and
**Ask**.

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

PDF, DOCX, TXT, Markdown, HTML. Unsupported types are rejected at upload. Extraction or embedding
failures leave the original document safely stored in OpenArch and are retryable from **Activity**.

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
