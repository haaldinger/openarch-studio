# Perceptive Content and OnBase connectors — design

Date: 2026-10-28 · Status: draft for review · Research: [perceptive-onbase-connectors](../../research/2026-10-28-perceptive-onbase-connectors.md)

## Purpose

Make content in Hyland Perceptive Content and Hyland OnBase searchable through Content Lake
([AlfrescoLabs/content-lake-app](https://github.com/AlfrescoLabs/content-lake-app)) with
permission-aware retrieval, built the way upstream builds connectors so the work can be contributed back.

Success means:

- Each source has a plugin jar that the batch ingester loads, built only against `content-lake-spi`.
- A user searching through the rag-service sees only content the configured mapping grants them, proven by
  an end-to-end test against a mock of each source.
- Every way the result differs from the source's own security is written down where operators will read it.
- The maintainers agree to the approach before code is written.

Not in scope: writing back to either source, change feeds, Perceptive or OnBase workflow, annotations,
or a "probe as each group" accurate mode (see the research doc).

## Constraints from the research

Neither API reports who may read a document, so readers come from an operator-configured mapping that
fails closed. The full list of limitations is in [Limitations](#limitations); they shape every section.

## Architecture

Work happens on one branch of a fork of content-lake-app.

| Piece | Location | Loaded by |
|---|---|---|
| Perceptive connector | `plugins/perceptive-connector/` (jar) | batch ingester, at runtime |
| OnBase connector | `plugins/onbase-connector/` (jar) | batch ingester, at runtime |
| Perceptive caller sign-in and groups | `rag-service/.../rag/security/Perceptive*.java` | rag-service, built in, off by default |
| OnBase caller sign-in and groups | `rag-service/.../rag/security/OnBase*.java` | rag-service, built in, off by default |
| End-to-end suite | `content-lake-app-deployment` | CI / local compose |

Rules carried over from upstream:

- Plugins are outside the Maven reactor and never added to the root POM. The SPI and Spring are `provided`;
  anything else is shaded.
- Java 25, JUnit 5, AssertJ, Mockito.
- No shared library between the two jars; each owns its settings record and mapping class. Similar code is
  accepted to keep the jars independent.
- Nothing is written to either source.

## Connector settings

Names follow the CMIS connector (`<sourceType>.<setting>`, constants in the plugin class, validated in a
settings record). Environment variables are the upper-cased form with dots and hyphens as underscores
(`perceptive.drawer-principals` → `PERCEPTIVE_DRAWER_PRINCIPALS`).

### Perceptive (`sourceType` = `perceptive`)

| Setting | Type | Required | Default | Notes |
|---|---|---|---|---|
| `perceptive.url` | URL | yes | | Integration Server base URL |
| `perceptive.username` | STRING | yes | | Read-only service account |
| `perceptive.password` | STRING, secret | yes | | Masked in schema output |
| `perceptive.source-id` | STRING | no | host of `url` | Namespaces principals |
| `perceptive.drawers` | LIST | yes | | Drawer names to walk |
| `perceptive.principals` | LIST | yes | | Mapping, see below |
| `perceptive.page-size` | INTEGER | no | 100 | Client-side paging of drawer listings |

### OnBase (`sourceType` = `onbase`)

| Setting | Type | Required | Default | Notes |
|---|---|---|---|---|
| `onbase.url` | URL | yes | | API Server core URL |
| `onbase.auth-url` | URL | yes | | IdentityService base URL |
| `onbase.client-id` | STRING | yes | | OAuth client |
| `onbase.scope` | STRING | yes | | Scope for the core API |
| `onbase.username` | STRING | yes | | Read-only service account |
| `onbase.password` | STRING, secret | yes | | Masked in schema output |
| `onbase.source-id` | STRING | no | host of `url` | Namespaces principals |
| `onbase.document-type-groups` | LIST | yes | | Type group names to walk |
| `onbase.principals` | LIST | yes | | Mapping, see below |
| `onbase.since` | STRING (ISO date) | no | 2000-01-01 | Earliest document date queried |
| `onbase.page-size` | INTEGER | no | 100 | Query `maxResults` per date window |

### Permission mapping

Each list entry is `<container>=<principal>|<principal>…`:

```
PERCEPTIVE_PRINCIPALS=Accounts Payable=group:AP Approver|user:tony,HR Records=group:HR
ONBASE_PRINCIPALS=Accounts Payable=group:AP Clerks,Human Resources=group:HR
```

- Entries are read with `ConnectorContext.listProperty`, so a single value is comma-separated; a name
  containing a comma needs the indexed form (`perceptive.principals[0]=…`).
- Containers are Perceptive drawer names, or OnBase document type group names. An OnBase entry may name a
  document type instead, which overrides its group's entry.
- `group:<name>`
  - Perceptive: resolved to the group id through `/v1/department` and `/v1/userGroup` at startup and
    emitted as `GROUP_<groupId>`. An unknown name stops startup with an error naming the entry.
  - OnBase: emitted as `GROUP_<name>` unchanged; cannot be validated (limitation 4).
- `user:<username>`: emitted unchanged. Perceptive usernames are checked against `/v2/user` at startup.
- `everyone`: emitted as `GROUP_EVERYONE`. Only ever explicit.
- A configured drawer or type group with no mapping entry is not walked and is reported as
  "skipped: no permission mapping" in the sync status. Nothing is ever ingested readable by everyone by
  default.

## How each source maps to the SPI

### Perceptive

| SPI | Perceptive |
|---|---|
| `getRootNodeIds` | Configured drawers (`drawer:<id>`), looked up by name at startup |
| `getChildren(drawer)` | `/v1/drawer/{id}`: folders and documents, paged client-side (`skip`/`max`) |
| `getChildren(folder)` | Folder contents; endpoint not yet probed (`/v5/folder/{id}` expected), confirm in the first task |
| Document → nodes | One `SourceNode` per page file: `page:<docId>:<pageId>`. A one-page document is named as the document; a multi-page one as `<name> — page n of N`. All pages carry `documentId` |
| `name` | Document name; when it is only the id, `<documentType> <field1> <field2>` |
| `mimeType` | From the page file extension |
| `modifiedAt` | Modification time from `/v7/document/{id}` |
| `readPrincipals` | From the drawer mapping |
| `sourceProperties` | Drawer, document type, `field1`–`field5`, custom properties, `documentId`, page number |
| `downloadContent` | `/v1/document/{id}/page/{pageId}/file`, copied to a fresh resource |
| Session | One session per client (`GET /v1/connection`), reused for every call, ended with `DELETE` on close. A 401 signs in again once, then fails |

Pages are separate nodes because the SPI carries one file per node; joining pages would need
format-specific merging in the connector, and first-page-only would drop content.

### OnBase

| SPI | OnBase |
|---|---|
| `getRootNodeIds` | Configured document type groups (`dtg:<id>`), looked up by name at startup |
| `getChildren(dtg)` | Its document types (`dt:<id>`) |
| `getChildren(dt)` | Documents through `POST /documents/queries` + `/results`, by document date windows from `onbase.since`. A window that returns `maxResults` items is split in half and re-queried, so the cap never truncates silently |
| `name` | Document name from the query results / `/documents/{id}` |
| `mimeType` | Content type of the rendition response |
| `modifiedAt` | `created` of the latest revision's default rendition; falls back to `storedDate` |
| `readPrincipals` | Document type entry if present, else the type group entry |
| `sourceProperties` | Type group, document type, `documentDate`, keywords (security-masked keyword types left out) |
| `downloadContent` | `/documents/{id}/revisions/latest` → `/revisions/{rev}/renditions/default/content` |
| Token | Password grant; refreshed on expiry. A 401 requests a new token once, then fails |

### Common behaviour

- Fail closed: if a document's container mapping cannot be resolved, the document is skipped and counted.
- `supportsChangeFeed()` is false for both; the host's walk plus `modifiedAt` decides what is re-read and
  its reconciliation pass handles deletions.
- `authState` reports a failed sign-in or an expired session that cannot be renewed.
- No `ScopeResolver` in the first version. No `TextExtractor`: content goes through the host's extraction.

## Search side (rag-service)

Mapped principals only match a caller if the rag-service gives that caller the same principals. Upstream
does this with built-in `CallerAuthenticator` and `SourceGroupResolver` beans that are switched on by
property (`@ConditionalOnProperty`), ordered by `CallerAuthenticatorOrder`, and whose groups are cached by
`SourceGroupResolverRegistry` (`rag.security.group-cache.ttl-seconds`). The additions copy the CMIS one.

| Bean | Enabled by | Behaviour |
|---|---|---|
| `PerceptiveCallerAuthenticator` (order 50) | `rag.security.perceptive.enabled=true` | Checks the caller's username and password with `GET /v1/connection`, then ends the session. Returns the Perceptive username as the user API reports it, scoped to `perceptive` |
| `PerceptiveGroupResolver` | same | Finds the user's groups by reading group memberships (`/v1/department`, `/v1/userGroup?departmentId=`, `/v1/userGroup/{id}`) with the configured service account; returns `GROUP_<groupId>`. Cached by the registry |
| `OnBaseCallerAuthenticator` (order 60) | `rag.security.onbase.enabled=true` | Password grant with the caller's credentials. Returns the username scoped to `onbase` and keeps the token's `group` claim values, if any, for the resolver |
| `OnBaseGroupResolver` | same | Returns `GROUP_<name>` for the groups captured at the caller's last sign-in (held no longer than the group cache TTL); none if the token had no `group` claim (limitation 9) |

Like the CMIS authenticator, both refuse reserved principals and blank passwords. New settings go in
`docs/configuration.md`, all off by default.

A contract test in each connector module and the rag-service asserts that, for the same user and group,
the connector's emitted principals and the resolver's output are identical strings.

## Testing

### Unit tests (each connector)

- Mapping parser: each principal form; unknown Perceptive group or user stops startup; unmapped container
  skipped and reported; document type entry overrides its group.
- Settings record: required fields, defaults, secret masking.
- Node mapping: names, properties, `modifiedAt` and its OnBase fallback, page naming.

### Mock servers

`MockPerceptiveServer.java` and `MockOnBaseServer.java`, each one dependency-free file on the JDK
`HttpServer`, run in process from tests and as a container with `java Mock….java`, like upstream's
`MockGraphServer`. Each is deliberately as awkward as the real service:

| Perceptive mock | OnBase mock |
|---|---|
| Limits concurrent sessions; connector must reuse and close one | Query returns 201 + handle, results fetched separately; results capped at `maxResults` with no hint |
| Sessions expire (401) | Tokens expire (401) |
| Drawer listings unpaged | Content only at `renditions/default/content`; `/file` is 404 |
| Document names that are just ids; mixed page file types | No modified date; masked keywords |
| Group privilege endpoint returns empty | `group` scope gives `invalid_scope` unless enabled |

Fixtures: one open and one restricted container, two users in two groups.

### End-to-end (`content-lake-app-deployment`)

Compose the ingester, both mocks and the rag-service, then:

1. Ingest the fixtures.
2. User A's search returns the restricted document; user B's does not.
3. Remove A's group from the mapping, re-sync: A no longer gets it.
4. Unmapped containers return nothing to anyone.

### Real-instance checklist (manual)

Documented in each README. Needs an administrator: two restricted test users in two groups, a restricted
and an open container, a read-only connector account; for OnBase, the `group` scope allowed for the
rag-service client. Run the four end-to-end checks against the real server. Each connector is labelled
**preview** until this passes.

## Documentation

- `plugins/perceptive-connector/README.md`, `plugins/onbase-connector/README.md`, following the archetype
  outline (Build and install, Configure it) plus: how content maps, **Limitations** near the top written as
  what the operator will observe, searching (the rag-service beans), and the real-instance checklist.
- `plugins/README.md`: two rows in the connector table, marked preview.
- `docs/security-model.md`: one section on sources that cannot report readers — configured, fail-closed
  mapping — linking to the two READMEs.
- `docs/configuration.md`: the rag-service properties.

## Upstream issue (opened before any code)

Title: "Perceptive Content and OnBase connectors (preview): configured permission mapping".

Body: the research summary; this design (architecture, mapping, rag-service additions, testing); all
limitations; and first, the question the work depends on: *are mapped-permission connectors acceptable,
or should they wait for source APIs that report readers?* Commits use `type: description`.

## Limitations

1. Neither API reports who may read a document; readers come from a configured mapping, and unmapped
   content is skipped.
2. The mapping is a copy, not a sync: source security changes reach the index only after the mapping is
   updated and content re-synced.
3. Finer source security is not reflected (Perceptive restrictions inside a drawer, OnBase security
   keywords); a mapped group may be granted documents some members cannot open in the source.
4. OnBase group names cannot be validated; a typo grants nothing.
5. Principals must exist in the caller's identity: callers must sign in with identities and groups that
   correspond to the source's.
6. No change feeds: the walk relies on `modifiedAt`; deletions come from host reconciliation.
7. Mocks and demo servers cannot prove permission behaviour; the connectors stay preview until the
   real-instance checklist passes.
8. Searching needs the rag-service beans, which are built in, not loaded from the plugin jars.
9. OnBase caller groups need the IdentityService client to allow the `group` scope; until then only user
   and everyone mappings match OnBase callers.
10. OnBase keyword-only edits create no revision, so they are not picked up until a new revision or a full
    re-sync.

## Open questions for review

- **Perceptive group scan cost.** Resolving a caller's groups reads every department's groups and their
  members. Fine for tens of groups; for hundreds, a periodic membership index may be needed. Measure on the
  real instance.
- **OnBase username form.** Whether the claim/username should be case-folded so it matches mapping
  entries; settle against the real instance.
- **Perceptive Integration Server licensing.** Whether each session consumes a licence, which decides
  whether the rag-service sign-in check is acceptable per search session.
- **OnBase resolver holding claim groups.** Upstream resolvers look groups up by username; carrying them
  from the token is new. Raise in the upstream issue.
