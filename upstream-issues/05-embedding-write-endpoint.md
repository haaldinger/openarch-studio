# Feature request: public embedding **write** endpoint (`POST .../embedding`)

## Summary
OpenArch exposes a read endpoint for embeddings (`GET .../embedding/{id}`), but
we couldn't find a public **write** endpoint. To attach embeddings to a document
we had to replicate OpenArch's internal mechanism: create a `SysEmbeddings` child
document carrying a Parquet blob that matches `embedding.avsc`, and add the
`SysHasEmbeddings` mixin to the parent. A first-class write endpoint would make
AI enrichment a supported, stable integration flow.

## What we do today (workaround)
1. Ensure the parent has the `SysHasEmbeddings` mixin.
2. Build a Parquet blob matching `embedding.avsc`
   (`id`, `type`, `vector` padded to `EmbeddingModel.VECTOR_SIZE` = 1024, `text`,
   `blobref`, `location`).
3. Upload the blob and create a `SysEmbeddings` child document (`_e_<type>`).
4. Wait for full-text/index propagation.

This works (it's the same shape OpenArch's own tests exercise), but it couples
external integrators to internal document structure and the exact Avro schema.

## Requested behaviour
A documented `POST .../embedding` (or equivalent) that accepts a document id, an
embedding-type label, and vectors+chunks, and performs the mixin + child-document
creation server-side — so integrators don't depend on `embedding.avsc` internals.

## Why it matters
Writing embeddings is the core of any "bring your own model" AI pipeline on top of
OpenArch. A supported write path makes OpenArch a first-class target for external
AI enrichment tools.

## Note
If such a write endpoint already exists and we missed it, a pointer in the docs
would resolve this. Found while building a POC that enriches OpenArch documents
with a local embedding model.
