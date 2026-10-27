# OpenArch Studio

A self-contained proof-of-concept that shows **OpenArch as a complete, permission-aware
AI-ready content platform** — and makes explicit which capabilities are OpenArch's own and
which are added on top.

One workflow, end to end:

> **sign in → upload → enrich → inspect → search → ask → open citation**

Upload a document; Studio stores it in OpenArch, extracts text with Docling (Tika as fallback),
chunks and embeds it with a local model, and writes the vectors back as an OpenArch `SysEmbeddings` child. Then search
it three ways and ask an agent questions whose answers are grounded in — and cited from — only the
content you're allowed to read.

## What's OpenArch vs. what Studio adds

| OpenArch native | Studio / open-source extension |
|---|---|
| Document & binary storage, metadata, content models | Visual content workspace |
| ACLs & effective permissions | Permission visualization |
| Keyword & advanced HXQL queries | Guided search interface |
| `SysEmbeddings` storage & vector search | Docling extraction (Tika fallback), chunking, embedding (Ollama) |
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
                 └─► Ollama      (OpenAI-compatible embeddings + chat)
```

| Service | Image | Role |
|---|---|---|
| `studio-web` | `./web` (nginx) | SPA on `${STUDIO_PORT:-8900}`; proxies `/api/*`. |
| `studio-api` | `./api` (FastAPI) | Session gateway, enrichment, search, RAG, graph. |
| `openarch-app` | OpenArch base compose | System of record. |
| `docling` | `quay.io/docling-project/docling-serve-cpu:v1.38.2` | Primary extractor. Not published to the host. |
| `tika` | `apache/tika:2.9.2.1-full` | Fallback extractor (Tesseract OCR). |
| `ollama` | `ollama/ollama:latest` | Local embeddings and chat. |

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
DOCX, TXT, Markdown, HTML, or image file, watch it enrich on the **Activity** page, then try
**Search** and **Ask**. The first Docling conversion is slow while it loads its models.

### Extraction settings

| Variable | Default | Purpose |
|---|---|---|
| `STUDIO_EXTRACTOR` | `docling` | `docling` (Tika fallback on failure) or `tika` only. |
| `STUDIO_DOCLING_URL` | `http://docling:5001` | docling-serve base URL. |
| `STUDIO_DOCLING_TIMEOUT_SECONDS` | `300` | Per-document Docling timeout; also caps docling-serve's sync wait. |

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
Docling extracts them (OCR for scanned images); Tika takes over for anything Docling can't process
(Docling's support for GIF and BMP is not verified, so those may be handled by Tika). Unsupported types are
rejected at upload. Extraction or embedding failures leave the original document safely stored in
OpenArch and are retryable from **Activity**.

Citations carry the source page. Clicking one opens `/documents/{id}?page=N`, and PDFs open at that
page in the browser's native viewer.

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
| Llama 3.1 | Chat model | Llama 3.1 Community License | [license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE) |
| Llama 3.2 | Knowledge-graph model | Llama 3.2 Community License | [license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE) |

Bundled in the Docling image, license not yet verified: EasyOCR model weights (`craft_mlt_25k`,
`english_g2`, `latin_g2`).

**Built with Llama.**

## License

Copyright 2026 Hyland. OpenArch Studio is released under the [Apache License 2.0](LICENSE), the
same license as OpenArch.
