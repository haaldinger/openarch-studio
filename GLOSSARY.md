# OpenArch Studio

The shared language of OpenArch Studio: a thin AI extension layered over
OpenArch, the system of record. These terms are specific to this project — they
name the boundary between what the platform owns and what Studio adds, the way
AI artifacts are stored, and how grounded answers and graphs are produced. They
deliberately exclude general programming concepts.

## Language

### Platform & ownership

**OpenArch**:
The open-source, AI-ready content platform that is the system of record for documents, permissions, and vectors.
_Avoid_: the platform, the backend, the server, the repository

**Studio**:
The proof-of-concept extension layered over OpenArch that adds the visual workspace and AI pipeline. Never a second source of truth.
_Avoid_: the app, OpenArch Studio (in prose), the product

**System of record**:
OpenArch's role as the single durable authority for documents, permissions, and AI artifacts; Studio's readiness is always reconstructable from it.
_Avoid_: source of truth, master, the database

**Native**:
A capability provided by OpenArch itself — storage, folders, permissions, HXQL, vector search.
_Avoid_: built-in, core, first-party

**Extension**:
A capability Studio adds on top of OpenArch — the workspace, OCR, chunking, embedding, search modes, grounded answers, the graph.
_Avoid_: feature, plugin, add-on

**Capability ledger**:
The strict, tested record attributing every capability to Native or Extension, rendered in the UI so the boundary is legible.
_Avoid_: feature list, capability matrix

**Session gateway**:
The server-side mechanism that validates a user's OpenArch credentials once and holds them in memory keyed by an opaque token, so the browser never holds credentials.
_Avoid_: auth proxy, login service, token service

**As the user**:
The principle that every OpenArch call runs with the signed-in user's own credentials — no service account and no elevation, so OpenArch's permissions are the single authority.
_Avoid_: on behalf of, impersonation, service account

### Storage model

**SysFile**:
The native OpenArch document that holds a source file's original bytes.
_Avoid_: document, blob, upload, file record

**SysEmbeddings**:
The native child document of a SysFile that carries that file's embeddings.
_Avoid_: embedding record, vector document, index entry

**SysFolder**:
The native OpenArch folder used for hierarchy and scoping.
_Avoid_: directory, collection

**Scope**:
A folder subtree that Search, Ask, and Graph can be confined to; the siloing mechanism.
_Avoid_: silo, filter, namespace, partition

**Chunk**:
A deterministic slice of a document's extracted text — the unit that gets embedded and cited.
_Avoid_: passage, segment, fragment, snippet

**Embedding**:
The vector representation of a chunk or query used for semantic retrieval.
_Avoid_: vector, encoding, representation

### Enrichment & retrieval

**Enrichment**:
The pipeline that turns an uploaded file into searchable, AI-ready artifacts, reported through its stages (stored, extracted, chunked, embedded, indexed, classified).
_Avoid_: ingestion, processing, indexing (for the whole pipeline)

**Extractor**:
The swappable component of the extracted stage that turns a file's bytes into page-aware Markdown text — Docling first, with Tika as the fallback.
_Avoid_: parser, converter, OCR engine, text reader

**Document type**:
The short snake_case label a model assigns to a document (for example `invoice`), reusing an
existing type from the caller's readable documents when one fits.
_Avoid_: category, class, kind

**Extracted fields**:
The typed name/value pairs a model reads from a document's text, stored in OpenArch's native
`CinContext` mixin alongside the document type and shown read-only as AI-extracted.
_Avoid_: metadata (loosely), attributes, tags, key-value pairs

**Readiness**:
Whether a document has been enriched — reconstructed from OpenArch, not from Studio's in-memory job history.
_Avoid_: status, state, progress

**HXQL**:
OpenArch's native query language, exposed directly as one of the search modes.
_Avoid_: query DSL, the query language

**Retrieve-then-verify**:
The discipline of ACL-filtering evidence at retrieval and re-fetching each cited document before answering, so an access change can't leak cached text.
_Avoid_: double-check, re-validation

**Grounded answer**:
An answer that cites only retrieved evidence, and declines with a fixed reply when there is none.
_Avoid_: response, completion, generation

**Citation**:
A reference in an answer that points to an actual retrieved chunk or document.
_Avoid_: source, reference (used loosely)

**Ask**:
The Studio surface for grounded, streaming question-and-answer over the corpus.
_Avoid_: chat, RAG (when naming the surface), assistant

### Knowledge graph

**Knowledge graph**:
The typed entity-and-relation graph extracted per document and merged under the caller's permissions.
_Avoid_: graph (used loosely), network, mind map

**Entity**:
A typed node in the knowledge graph, drawn from the fixed ontology.
_Avoid_: node (for a domain entity), thing, object

**Ontology**:
The fixed set of entity types the graph extractor is constrained to.
_Avoid_: schema, taxonomy, the types
