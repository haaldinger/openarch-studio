# AGENTS.md

OpenArch Studio — a proof of concept that overlays a working UI and a
retrieval-augmented AI pipeline on top of [OpenArch](./README.md), the
open-source, AI-ready content platform. Studio is a *thin extension*: OpenArch
stays the system of record, and every AI capability runs as the signed-in user.

- `api/` — FastAPI backend-for-frontend (session gateway, enrichment, `extraction.py` Docling/Tika extractors, `fields.py` classification + extracted fields, `rerank.py` cross-encoder reranking, search, RAG, graph)
- `web/` — React + TypeScript SPA (Vite), served by nginx
- `eval/` — `studio-eval` evaluation harness (golden set, retrieval/abstention metrics, Ragas grading)
- `docs/` — technical deep dive

See [`docs/TECHNICAL-DEEP-DIVE.md`](./docs/TECHNICAL-DEEP-DIVE.md) for the full
architecture and design rationale.

## Agent skills

### Issue tracker

Issues live as GitHub issues in `haaldinger/openarch-studio` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical triage vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
