# Perceptive Content and OnBase connectors — design

Date: 2026-10-28 · Status: draft for review · Research: [perceptive-onbase-connectors](../../research/2026-10-28-perceptive-onbase-connectors.md)

## Purpose

Make content in Hyland Perceptive Content and Hyland OnBase searchable through Content Lake
([AlfrescoLabs/content-lake-app](https://github.com/AlfrescoLabs/content-lake-app)) with
permission-aware retrieval, built the way upstream builds connectors so the work can be contributed back.

Success means:

- Each source has a plugin jar that the batch ingester loads, built only against `content-lake-spi`.
- A user searching through the rag-service sees only content the source's privileges (Perceptive) or the
  configured mapping (OnBase) grants them, proven by an end-to-end test against a mock of each source.
- Every way the result differs from the source's own security is written down where operators will read it.
- The maintainers agree to the approach before code is written.

Not in scope: writing back to either source, change feeds, Perceptive or OnBase workflow, annotations,
or a "probe as each group" accurate mode (see the research doc).

## Constraints from the research

- **Perceptive** reports privileges per drawer and per document type for each group and user, as
  `GRANTED`, `DENIED` or `UNSET`, through free calls. Readers are computed from those.
- **OnBase** reports no readers at all, so readers come from an operator-configured mapping that fails
  closed.
- **Content Lake does not enforce deny principals** (`docs/security-model.md`), so any deny-wins rule must
  be resolved inside the connector, which then emits only who can read.

The full list of limitations is in [Limitations](#limitations); they shape every section.

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
(`onbase.document-type-groups` → `ONBASE_DOCUMENT_TYPE_GROUPS`).

### Perceptive (`sourceType` = `perceptive`)

| Setting | Type | Required | Default | Notes |
|---|---|---|---|---|
| `perceptive.url` | URL | yes | | Integration Server base URL |
| `perceptive.username` | STRING | yes | | Read-only service account |
| `perceptive.password` | STRING, secret | yes | | Masked in schema output |
| `perceptive.source-id` | STRING | no | host of `url` | Namespaces principals |
| `perceptive.drawers` | LIST | yes | | Drawer names to walk |
| `perceptive.views` | LIST | yes | | `<drawer>=<document view name>`; the view used to search that drawer. One entry `*=<view>` applies to all drawers without their own |
| `perceptive.unreadable-groups` | ENUM `skip-drawer`, `ignore` | no | `skip-drawer` | What to do when the account cannot read some groups' privileges (limitation 13) |

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
| `onbase.page-size` | INTEGER | no | 100 | Documents kept per query; each query asks for one more to detect the cap |

### Perceptive readers (computed from the source)

Built once per sync into a privilege index for the configured drawers and the document types met during
the walk, from free calls: groups (`/v1/department`, `/v1/userGroup?departmentId=`, members from
`/v2/userGroup/{id}`), users (`/v2/user`), and
`/v2/userGroup/{id}/privilege` / `/v2/user/{id}/privilege` with `drawerId` or `documentTypeId`.

For a document in drawer *D* with document type *T*, following Hyland's privilege rules:

1. For each of *D* and *T*, a principal's setting of the open/view privilege (`DOC_VIEW` in the API) is
   its user-level value if set, otherwise the combination of its groups' values: any `DENIED` wins, then
   any `GRANTED`, otherwise `UNSET`.
2. A user can read the document if neither *D* nor *T* is `DENIED` for them and at least one is `GRANTED`.
   `UNSET` is a soft deny.
3. Emitted `readPrincipals`:
   - when no group or user has `DENIED` and no user-level setting exists for *D* or *T*: the granted
     groups as `GROUP_<groupId>` plus any granted users;
   - otherwise: the individual users who pass rule 2 (usernames), because a group grant cannot exclude a
     denied member once Content Lake ignores denies.
4. `denyPrincipals` carries the denied users and groups for diagnostics only (`cin_deny`).

Groups the account cannot read ("not owned by or shared with the current department") make the result
uncertain. With `skip-drawer` (default) such a drawer is skipped and reported, listing the unreadable
groups; with `ignore` they are left out and the operator accepts the risk.

### OnBase permission mapping

Each list entry is `<container>=<principal>|<principal>…`:

```
ONBASE_PRINCIPALS=Accounts Payable=group:AP Clerks,Human Resources=group:HR
```

- Entries are read with `ConnectorContext.listProperty`, so a single value is comma-separated; a name
  containing a comma needs the indexed form (`onbase.principals[0]=…`).
- Containers are document type group names; an entry may name a document type instead, which overrides
  its group's entry.
- `group:<name>`: emitted as `GROUP_<name>` unchanged; cannot be validated (limitation 4).
- `user:<username>`: emitted unchanged, matching the token's `username` claim.
- `everyone`: emitted as `GROUP_EVERYONE`. Only ever explicit.
- A configured type group with no mapping entry is not walked and is reported as
  "skipped: no permission mapping" in the sync status. Nothing is ever ingested readable by everyone by
  default.

## How each source maps to the SPI

### Perceptive

| SPI | Perceptive |
|---|---|
| `getRootNodeIds` | Configured drawers (`drawer:<id>`), looked up by name at startup; a drawer without a usable view stops startup |
| `getChildren(drawer)` | Every document in the drawer, flat: `POST /v6/view/{id}/result?category=DOCUMENT` with VSL `[drawer] = '<name>'`. Results stop at 500 with `hasMore`; a part with `hasMore=true` is split by `[docId]` ranges and re-run until every part has `hasMore=false`. `skip`/`max` page over the collected ids. Folders are not modelled in the first version |
| Document → nodes | One `SourceNode` per page file: `page:<docId>:<pageId>`. A one-page document is named as the document; a multi-page one as `<name> — page n of N`. All pages carry `documentId` |
| `name` | Document name; when it is only the id (18 of 25 sampled), `<documentType> <field1> <field2>` |
| `mimeType` | From the page file extension |
| `modifiedAt` | Modification time from `/v7/document/{id}`, else creation time (11 of 25 sampled had none) |
| `readPrincipals` | Computed, see [Perceptive readers](#perceptive-readers-computed-from-the-source) |
| `sourceProperties` | Drawer, document type, `field1`–`field5`, custom properties, `documentId`, page number |
| `downloadContent` | `/v1/document/{id}/page/{pageId}/file`, copied to a fresh resource |
| Session | One session for the connector (`GET /v1/connection`), reused for every call (Integration Server runs one call at a time per session), ended with `DELETE` on close. A 401 signs in again once, then fails |
| Cost | Document, page and file calls are charged against the transaction licence; privilege, user, group and connection calls are free. The sync status reports charged calls per run |

Pages are separate nodes because the SPI carries one file per node; joining pages would need
format-specific merging in the connector, and first-page-only would drop content.

### OnBase

| SPI | OnBase |
|---|---|
| `getRootNodeIds` | Configured document type groups (`dtg:<id>`), looked up by name at startup. A group the account cannot query (400) is reported and skipped |
| `getChildren(dtg)` | Its document types (`dt:<id>`) |
| `getChildren(dt)` | Documents through `POST /documents/queries` (`DocumentType`, `documentDateRangeCollection`) + `/results`, by document date windows from `onbase.since`. Each query asks for `page-size + 1`; getting more than `page-size` back means the window is split in half and re-queried. OnBase reports no truncation itself |
| `name` | The `Document Name` display column of the query results |
| `mimeType` | Content type of the rendition response |
| `modifiedAt` | `created` of the latest revision's default rendition; falls back to `storedDate` |
| `readPrincipals` | Document type entry if present, else the type group entry |
| `sourceProperties` | Type group, document type, `documentDate`, keywords (security-masked keyword types left out) |
| `downloadContent` | `/documents/{id}/revisions/latest` → `/revisions/{rev}/renditions/default/content` |
| Token | Password grant; refreshed on expiry. A 401 requests a new token once, then fails |

### Common behaviour

- Fail closed: a document whose readers cannot be determined (Perceptive) or whose container has no
  mapping (OnBase) is skipped and counted, never ingested readable by everyone.
- `supportsChangeFeed()` is false for both; the host's walk plus `modifiedAt` decides what is re-read and
  its reconciliation pass handles deletions.
- `authState` reports a failed sign-in or an expired session that cannot be renewed.
- No `ScopeResolver` in the first version. No `TextExtractor`: content goes through the host's extraction.

## Search side (rag-service)

Emitted principals only match a caller if the rag-service gives that caller the same principals. Upstream
does this with built-in `CallerAuthenticator` and `SourceGroupResolver` beans that are switched on by
property (`@ConditionalOnProperty`), ordered by `CallerAuthenticatorOrder`, and whose groups are cached by
`SourceGroupResolverRegistry` (`rag.security.group-cache.ttl-seconds`). The additions copy the CMIS one.

| Bean | Enabled by | Behaviour |
|---|---|---|
| `PerceptiveCallerAuthenticator` (order 50) | `rag.security.perceptive.enabled=true` | Checks the caller's username and password with `GET /v2/connection` (free; returns the user's id and name), then ends the session. Returns that username, scoped to `perceptive` |
| `PerceptiveGroupResolver` | same | `GET /v1/user/{id}/group` with the configured service account (one call; the id comes from `/v2/user`, cached); returns `GROUP_<groupId>`. Cached by the registry |
| `OnBaseCallerAuthenticator` (order 60) | `rag.security.onbase.enabled=true` | Password grant with the caller's credentials. Returns the token's `username` claim (equal to the login name), scoped to `onbase`, and keeps the `group` claim values, if any, for the resolver |
| `OnBaseGroupResolver` | same | Returns `GROUP_<name>` for the groups captured at the caller's last sign-in (held no longer than the group cache TTL); none if the token had no `group` claim (limitation 9) |

Like the CMIS authenticator, both refuse reserved principals and blank passwords. New settings go in
`docs/configuration.md`, all off by default.

A contract test in each connector module and the rag-service asserts that, for the same user and group,
the connector's emitted principals and the resolver's output are identical strings.

## Testing

### Unit tests (each connector)

- Perceptive reader rules: user setting beats group; deny wins across groups and across drawer and
  document type; `UNSET` alone grants nothing; groups emitted when there are no exceptions, users when
  there are; unreadable groups with `skip-drawer` and `ignore`.
- OnBase mapping parser: each principal form; unmapped type group skipped and reported; document type
  entry overrides its group.
- Settings record: required fields, defaults, secret masking.
- Node mapping: names, properties, `modifiedAt` and its fallbacks, page naming.
- Splitting: Perceptive view results over 500 and OnBase windows over `page-size` are split until
  complete, with no document lost or duplicated.

### Mock servers

`MockPerceptiveServer.java` and `MockOnBaseServer.java`, each one dependency-free file on the JDK
`HttpServer`, run in process from tests and as a container with `java Mock….java`, like upstream's
`MockGraphServer`. Each is deliberately as awkward as the real service:

| Perceptive mock | OnBase mock |
|---|---|
| One call at a time per session; sessions expire (401) | Query returns 201 + handle, results fetched separately; returns as many as `maxResults` asks, never says it truncated |
| Drawer listings and view results stop at 500; views set `hasMore` and accept `[docId]` ranges | Tokens expire (401) |
| Privilege calls return an empty list without `drawerId`/`documentTypeId`; some groups answer 400 "not owned by the current department" | Content only at `renditions/default/content`; `/file` is 404 |
| Counts charged vs free calls so tests can assert a crawl's transaction cost | No modified date; masked keywords; some type groups answer 400 |
| Document names that are just ids; documents without a modification time; mixed page file types | `group` scope gives `invalid_scope` unless enabled |

Fixtures: an open and a restricted container, two users in two groups; for Perceptive also a user-level
deny inside a granted group and a document type that denies what its drawer grants.

### End-to-end (`content-lake-app-deployment`)

Compose the ingester, both mocks and the rag-service, then:

1. Ingest the fixtures.
2. User A's search returns the restricted document; user B's does not.
3. Remove A's access (Perceptive: change the group privilege in the mock; OnBase: the mapping), re-sync: A
   no longer gets it.
4. Perceptive: the user denied inside a granted group does not get the document; neither does anyone for
   the document type that denies.
5. Unmapped (OnBase) or undeterminable (Perceptive) containers return nothing to anyone.

### Real-instance checklist (manual)

Documented in each README. Needs an administrator: two restricted test users in two groups, a restricted
and an open container, a read-only connector account; for Perceptive also one user-level deny and one
document-type deny; for OnBase, the `group` scope allowed for the rag-service client. Run the end-to-end
checks against the real server, and for Perceptive compare the computed readers with what each test user
can actually open in the client. The test users must be ordinary accounts: department managers open
content without privileges, so the configured demo account (a manager of nearly every department) cannot
validate the rules. Each connector is labelled **preview** until this passes.

## Documentation

- `plugins/perceptive-connector/README.md`, `plugins/onbase-connector/README.md`, following the archetype
  outline (Build and install, Configure it) plus: how content maps, **Limitations** near the top written as
  what the operator will observe, searching (the rag-service beans), and the real-instance checklist.
- `plugins/README.md`: two rows in the connector table, marked preview.
- `docs/security-model.md`: one section on sources whose readers come from privileges the connector
  resolves itself (Perceptive, deny resolved before emission) or from a configured, fail-closed mapping
  (OnBase), linking to the two READMEs.
- `docs/configuration.md`: the rag-service properties.

## Upstream issue (opened before any code)

Title: "Perceptive Content and OnBase connectors (preview): source-computed and mapped permissions".

Body: the research summary; this design (architecture, reader computation and mapping, rag-service
additions, testing); all limitations; and first, the questions the work depends on: *is a configured
mapping acceptable for OnBase, or should it wait for an API that reports readers?* and *is resolving
Perceptive's deny-wins privileges in the connector (expanding to users when needed) the right place,
given that `cin_deny` is not enforced?* Commits use `type: description`.

## Limitations

1. OnBase reports no readers; its readers come from a configured mapping, and unmapped content is
   skipped. Perceptive readers are computed from drawer and document type privileges.
2. Security is copied at sync time: mapping, privilege and membership changes reach the index only when
   the content is re-synced; privilege changes do not change a document's modification time.
3. Finer source security is not reflected: OnBase security keywords; in Perceptive anything beyond drawer
   and document type privileges (folder type, view, category privileges).
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
11. Perceptive crawls spend the customer's Integration Server transaction licence (document, page and file
    calls); privilege, user, group and connection calls are free.
12. Perceptive listings stop at 500 with no paging; the connector splits searches and needs a document
    view per drawer that the service account can run. Folder structure is not reproduced.
13. Perceptive privileges are department-scoped; groups the account cannot read make a drawer's readers
    uncertain, and by default that drawer is skipped.
14. Perceptive department managers and owners, who open content through management rights rather than
    privileges, are not granted it in the index unless they also hold the privileges.

## Open questions for review

- **Perceptive grant across drawer and document type.** The rules above treat a grant on either the drawer
  or the document type as enough (deny on either wins). Hyland's text states the deny half explicitly;
  confirm the grant half on the real instance.
- **Perceptive unreadable groups.** Whether a group not shared with a department can hold privileges in
  that department's drawers at all. If not, `ignore` is safe and could become the default.
- **Perceptive privilege name.** Confirm that `DOC_VIEW` is the API name for Documents > Open.
- **OnBase resolver holding claim groups.** Upstream resolvers look groups up by username; carrying them
  from the token is new. Raise in the upstream issue.
