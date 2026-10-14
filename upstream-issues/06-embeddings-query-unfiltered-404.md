# Bug: `POST /api/query/embeddings` returns 404 for an unfiltered kNN query

## Summary
On OpenArch `1.0.0`, a kNN embeddings query (`POST /api/query/embeddings`) fails
with **HTTP 404** when the HXQL statement has **no `WHERE` filter** that pins it
to specific documents. The *same* vector + embedding type succeeds (**HTTP 200**,
ranked neighbours) as soon as the statement is scoped to a single document by
`sys_id`. This makes "search the whole repository by meaning" impossible through
the public embeddings endpoint without first enumerating candidate documents.

## Environment
- OpenArch `1.0.0` (single-node `docker compose`, DBS backend).
- Embeddings written as `SysEmbeddings` children (`SysHasEmbeddings` mixin),
  `nomic-embed-text`, 1024-dim vectors.

## Repro
With a document that has embeddings (`sys_id = <DOC_ID>`):

```bash
# 1) FILTERED query — succeeds (HTTP 200, returns ranked neighbours)
curl -sS -u admin:password -X POST "$OA/api/query/embeddings" \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "SELECT * FROM SysContent WHERE sys_id = '"'"'<DOC_ID>'"'"'",
        "embeddingType": "nomic-embed-text*",
        "vector": [ ... 1024 floats ... ],
        "limit": 10
      }'

# 2) UNFILTERED query — same vector / type — fails (HTTP 404)
curl -sS -u admin:password -X POST "$OA/api/query/embeddings" \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "SELECT * FROM SysContent",
        "embeddingType": "nomic-embed-text*",
        "vector": [ ... same 1024 floats ... ],
        "limit": 10
      }'
```

The 404 is independent of the vector contents, the vector dimensionality
(768 vs 1024 both 404 when unfiltered), and the `embeddingType` wildcard — the
only variable that flips 200 ↔ 404 is the presence of a document-scoping
`WHERE` clause.

## Expected
An unfiltered embeddings query should return the global nearest neighbours across
all documents the caller may read (ACL-filtered), or at minimum return `200` with
an empty/partial result set — not a `404`.

## Actual
`404 Not Found` for any embeddings query that is not pinned to specific
document ids.

## Workaround (shipped in our POC)
We enumerate embedded documents first, then run the kNN query **per document** and
merge:

1. `POST /api/query` with
   `SELECT * FROM SysContent WHERE sys_mixinTypes = 'SysHasEmbeddings'`
   (optionally `AND sys_ancestorIds = '<scope>'`) — this is ACL-filtered and
   works. Collect the `sys_id`s.
2. For each id, `POST /api/query/embeddings` with
   `SELECT * FROM SysContent WHERE sys_id = '<id>'` + the query vector.
3. Merge hits, sort by `sysembed_score` desc, take top-N.

This restores whole-repository semantic search, but it is O(documents) requests
and defeats the point of a single global kNN call.

## Why it matters
Whole-corpus semantic search is the primary use case for the embeddings endpoint.
If an unfiltered query can't run, every external RAG/search integration has to
reimplement fan-out and merging client-side.

## Note
If an unfiltered global kNN is intentionally unsupported and there is a different
documented entry point for it, a pointer in the docs would resolve this. Found
while building a POC that does grounded search/chat over OpenArch content.
