# Limitation: `EmbeddingModel.VECTOR_SIZE` is hardcoded to 1024 — rejects larger models, silently pads smaller ones

## Summary
OpenArch's embedding storage uses a fixed vector width,
`EmbeddingModel.VECTOR_SIZE = 1024`. Vectors **longer** than 1024 are **rejected**,
and vectors **shorter** than 1024 must be **zero-padded** up to 1024 before they
are accepted. This hardcoded width constrains which embedding models can be used
with OpenArch and forces integrators to reshape their vectors to match an internal
constant.

## Environment
- OpenArch `1.0.0` (single-node `docker compose`, DBS backend).
- Embeddings stored as `SysEmbeddings` children (`SysHasEmbeddings` mixin),
  Parquet blob matching `embedding.avsc`.
- Observed while writing embeddings from `nomic-embed-text` (native **768-dim**).

## Behaviour today
1. **Larger models are unusable.** An embedding model that produces vectors wider
   than 1024 (e.g. OpenAI `text-embedding-3-large` = **3072**, many modern models
   = 1536+) cannot be stored at all — the write path rejects the longer vector.
2. **Smaller models are silently zero-padded.** A model narrower than 1024 (e.g.
   `nomic-embed-text` = 768) only works if the caller pads every vector to exactly
   1024. The padding is not performed/validated for the integrator at the public
   boundary, so this is undocumented behavior an external pipeline must discover.
3. **Query vectors must match.** Because stored vectors are padded to 1024, the
   query vector must be padded to 1024 identically, or kNN dimensions disagree at
   search time. (In our POC, `normalize_vector()` pads both stored and query
   vectors to 1024 so they always agree.)

## Expected / requested
One of:
- Make the vector width **configurable** (per repository or per embedding type)
  instead of a single hardcoded 1024, so larger models are supported; **or**
- Have the server **accept the model's native width** and store the true
  dimensionality alongside each embedding type (padding/truncation handled and
  documented server-side); **or**
- At minimum, **document** the fixed 1024 width and the padding requirement at the
  public embeddings boundary, and return a clear validation error (not silent
  acceptance) when a vector's native width ≠ the expected width.

## Why it matters
The embedding width effectively dictates which models an integrator may bring.
A hardcoded 1024 excludes a large and growing set of popular embedding models
(1536/3072-dim) and makes the "bring your own model" story depend on an internal
constant. Documenting it — or, better, making it configurable — removes a sharp
edge for every external AI/RAG integration.

## References
- `modules/platform/openarch-opensearch/.../schemas/embedding.avsc` (embedding
  row shape).
- `EmbeddingModel.VECTOR_SIZE` (the hardcoded `1024`).

## Note
Related to the embedding **write** path discussed in #5 and the embeddings
**query** behavior in the companion kNN issue. Found while building a POC that
enriches OpenArch documents with a local embedding model.
