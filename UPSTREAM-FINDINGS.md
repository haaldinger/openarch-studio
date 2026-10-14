# OpenArch Studio — Findings & Upstream Candidates

Captured 2026-10-13 while building and deploying the Studio POC against a
locally-built OpenArch (`12.0-SNAPSHOT`, from source). Reference for later;
nothing here blocks the POC.

## How this OpenArch was deployed

The published image `ghcr.io/hyland/openarch-app-jvm` was **not anonymously
pullable** (`unauthorized`; authenticated as a non-org account → `denied`), so
OpenArch was built from source:

```bash
brew install openjdk@25 maven
cd OpenArch-main
git init && git add -A && git commit -m snapshot    # build needs SCM metadata
JAVA_HOME=/opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home \
  mvn -q -DskipTests -T1C package
# minimal public-base image (official Dockerfile needs a gated dhi.io base + release-only licenses)
docker build -f server/openarch-app/Dockerfile.local \
  -t ghcr.io/hyland/openarch-app-jvm:1.0.0 server/openarch-app
```

`server/openarch-app/Dockerfile.local` is the throwaway dev image used for this.

## Upstream candidates (OpenArch product repo)

> **Filed 2026-10-13** on [Hyland/OpenArch](https://github.com/Hyland/OpenArch):
> #1 build-without-git, #2 dev Dockerfile, #3 version inconsistency,
> #4 image visibility, #5 embedding write endpoint. Draft bodies in
> [`upstream-issues/`](./upstream-issues). Finding #6 (full-text) stays in the
> Studio repo as issue #1 pending root-cause.
>
> **Draft 2026-10-14 (not yet filed):** #7 embeddings query 404s when
> unfiltered — draft in
> [`upstream-issues/06-embeddings-query-unfiltered-404.md`](./upstream-issues/06-embeddings-query-unfiltered-404.md).
> Studio-repo drafts (graph cold-start, heavy default chat model) in
> [`studio-issues/`](./studio-issues).


### Build / packaging robustness — strong PR candidates
1. **Source build fails without `.git`.** `buildnumber-maven-plugin` and
   `git-commit-id-maven-plugin:revision` both hard-fail on a source download
   (no `.git`). `git-commit-id` ignored `-Dgit.skip=true`. A download-and-build
   user is blocked until they `git init`. Fix: honor skip flags /
   `failOnNoGitDirectory=false`, or degrade gracefully.
2. **Official Dockerfile can't build from a plain `mvn package`** despite its
   header saying so: it needs a gated `dhi.io/amazoncorretto` base and
   `target/licenses` + `target/*-3rd-Party-libraries.csv` produced only by the
   release/license profile. A dev-profile Dockerfile on a public base would let
   anyone build+run locally.
3. **Version inconsistency:** `VERSION` file says `1.0`; root POM is
   `12.0-SNAPSHOT`; README references image tag `1.0.0`.
4. **Published image visibility:** if the ghcr image is meant to back the
   README "clone and `docker-compose up`" story, it needs anonymous pull (or the
   README should document the required `docker login` + org access).

### Product feature suggestions — issues
5. **No public embedding *write* endpoint.** Only `GET .../embedding/{id}`
   exists. Studio writes embeddings by creating a `SysEmbeddings` child document
   with a Parquet blob (matching `embedding.avsc`) + the `SysHasEmbeddings`
   mixin — the internal capability OpenArch's own tests exercise. A first-class
   `POST .../embedding` would make AI enrichment a supported flow.
6. **Server-side full-text extraction not populating in single-node compose.**
   With `nuxeo.dbs.fulltext.disabled=false` (default) and the `fulltextExtractor`
   async task enabled, an uploaded `text/plain` `SysFile` still yields
   `sys_fulltext = '<term>'` → 0 results, and the document carries no extracted
   fulltext property (only `sysfile_blob`). Needs investigation: is binary text
   extraction wired in this deployment, or does it require a transform/converter
   service that isn't present? Studio sidesteps this by doing its own Tika
   extraction + embedding, so semantic search and chat work regardless.
7. **Embeddings query 404s when unfiltered (OpenArch 1.0.0).**
   `POST /api/query/embeddings` returns `404` for a kNN query with no
   document-scoping `WHERE` (`SELECT * FROM SysContent`); the identical vector +
   type returns `200` once scoped to a `sys_id`. Blocks whole-repository semantic
   search via the public endpoint. Studio works around it by enumerating embedded
   docs (`SysHasEmbeddings`) and running per-doc kNN, then merging. Draft:
   [`upstream-issues/06-embeddings-query-unfiltered-404.md`](./upstream-issues/06-embeddings-query-unfiltered-404.md).

## Studio-side notes
- **Keyword search** depends on #6. Workaround shipped: keyword mode searches the
  chunk text Studio indexed in OpenArch's embeddings index (`chunkFTS`), which is
  content-based and works in this deployment. Revisit if/when server-side
  fulltext extraction is confirmed working.
- **Studio stays an external consumer** (API-first), not merged into core. It
  could be contributed to the OSS org as a second reference app beside
  `content-lake-app-deployment` — "build directly on OpenArch" vs. that repo's
  "enterprise multi-source" example.
