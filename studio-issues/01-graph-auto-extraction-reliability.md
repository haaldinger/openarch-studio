# Bug: knowledge-graph auto-extraction silently fails on a cold model

## Summary
When a document is enriched, Studio kicks off knowledge-graph extraction in the
background. If the graph model (`llama3.2:1b` by default) has not been warmed up
yet, that first extraction call can fail and the failure is swallowed — so the
Graph tab shows nothing for a freshly enriched document, with no error surfaced
to the user. (Graph **persistence** itself works: once a graph is built it
survives `studio-api` restarts via the `studio-data` volume.)

## Environment
- Studio POC, `studio-api` with Ollama, graph model `llama3.2:1b`.
- `STUDIO_GRAPH_STORE_PATH=/data/graph.json` on a named volume (persistence OK).

## Repro
1. Cold-start the stack (model not yet loaded in Ollama).
2. Upload + enrich a document.
3. Open the **Graph** tab immediately → empty, no entities, no error toast.
4. The enrichment pipeline reported success; only the graph is missing.

## Root cause
The auto-extraction step runs during/just after enrichment while the model is
still cold. The call throws (model load timeout / first-token latency), the
exception is caught and ignored, and no graph is persisted for that document. The
user has no signal that extraction didn't happen.

## Fix shipped (self-heal on view)
`GET /api/graph` now self-heals: for every embedded document in scope that has no
stored graph, it rebuilds the graph from the document's chunk text on demand and
then returns the merged graph. Verified: a graph (4 nodes / 3 edges) built this
way persists across multiple `studio-api` restarts.

```
GET /api/graph
  → list embedded docs in scope
  → for each doc with no stored graph: extract from chunk text, store
  → return merged graph
```

## Remaining work / suggestions
- Surface extraction failures instead of swallowing them (log + a visible
  "graph pending/failed, retry" state in the UI).
- Warm the graph model on startup, or make the first extraction retry with
  backoff, so the cold-start path isn't silently empty.
- Consider extracting lazily on first Graph view by default (the self-heal path),
  rather than eagerly during enrichment.

## Why it matters
A silently-empty Graph tab reads as "the feature doesn't work" to anyone
demoing or evaluating Studio, even though the pipeline and persistence are fine.

## Resolution
The API now warms the extract model (and chat model) in the background at startup,
so the first extraction no longer hits a cold model; the on-view self-heal remains
as the fallback. Graph extraction now uses `STUDIO_EXTRACT_MODEL` (the old
`STUDIO_GRAPH_MODEL` is still accepted as an alias).
