# OnBase connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Content Lake plugin that ingests OnBase documents through the Hyland API Server, with readers from an operator-configured, fail-closed mapping, plus the rag-service sign-in that gives OnBase callers matching principals.

**Architecture:** A shaded plugin jar in `plugins/onbase-connector/` walks configured document type groups → document types → documents found by date-windowed queries (asking for one more than a page to detect OnBase's silent cap), downloads the latest revision's default rendition, and assigns readers from the mapping. Two `@ConditionalOnProperty` beans in `common/rag-service` sign callers in with a password grant and carry the token's `group` claim to the resolver. A dependency-free `MockOnBaseServer` reproduces the API's traps.

**Tech Stack:** Java (compile `release 21`, build with JDK 25), Maven, JDK `HttpClient`, Jackson 2.22.0 (shaded), JUnit 5, AssertJ, Mockito; Spring Boot in rag-service; bash + docker compose for end-to-end.

**Spec:** `docs/superpowers/specs/2026-10-28-perceptive-onbase-connectors-design.md` (OnBase parts). Research: `docs/research/2026-10-28-perceptive-onbase-connectors.md`.

## Global Constraints

- Builds on the forks, branch and toolchain from the Perceptive plan's Task 0 (`docs/superpowers/plans/2026-10-28-perceptive-connector.md`); run that task first if this plan executes alone.
- `export JAVA_HOME=$(brew --prefix openjdk@25)` before every Maven command.
- Plugin coordinates `org.hyland.contentlake:onbase-connector:1.0.0`, package `org.hyland.contentlake.connector.onbase`, `sourceType` = `onbase`. Pom mirrors `plugins/sharepoint-connector/pom.xml` without `msal4j`; never added to the root POM.
- Settings exactly as the spec's OnBase table: `onbase.url`, `onbase.auth-url`, `onbase.client-id`, `onbase.scope`, `onbase.username`, `onbase.password` (secret), `onbase.source-id` (default host of url), `onbase.document-type-groups`, `onbase.principals`, `onbase.since` (default `2000-01-01`), `onbase.page-size` (default 100).
- Nothing is ever written to OnBase: only GET, the token request and `POST /documents/queries`.
- Fail closed: a type group without a mapping entry is not walked and is logged at WARN as `skipped: no permission mapping`; nothing is ingested readable by everyone unless the mapping says `everyone`.
- Principals: `group:<name>` → `GROUP_<name>`; `user:<username>` → `<username>`; `everyone` → `GROUP_EVERYONE`.
- Commits: `type: short description`.

## Review Focus

1. **More than `page-size` documents on a single day** (date windows cannot split further) → expected: that day is re-queried with `maxResults` 10001; more than 10000 → `ListingIncompleteException`, not a silent cut. Test in Task 4.
2. **Configured type group the account cannot query** (400 "Failed to add DocumentTypeGroup") → expected: WARN and skip that group, others continue. Test in Task 5.
3. **Mapping entry naming a type group or type that does not exist** → expected: startup fails naming the entry (a typo otherwise grants nothing silently). Test in Task 1/5.
4. **Rendition with no `Content-Type`** → expected: `application/octet-stream`, document still ingested. Test in Task 5.
5. **Token expiry mid-walk** → expected: one new token, walk continues; second consecutive 401 fails. Test in Task 3.

---

### Task 1: Module, settings, schema and mapping

**Files:**
- Create: `plugins/onbase-connector/pom.xml`
- Create: `.../connector/onbase/OnBaseConnectorPlugin.java`, `.../onbase/OnBaseSettings.java`, `.../onbase/PrincipalMapping.java`
- Create: `plugins/onbase-connector/src/main/resources/META-INF/services/org.hyland.contentlake.spi.ConnectorPlugin`
- Test: `.../onbase/OnBaseSettingsTest.java`, `.../onbase/PrincipalMappingTest.java`

**Interfaces:**
- Produces: `record OnBaseSettings(URI url, URI authUrl, String clientId, String scope, String username, String password, String sourceId, List<String> documentTypeGroups, PrincipalMapping principals, LocalDate since, int pageSize)` with `static OnBaseSettings from(ConnectorContext ctx)`.
- Produces: `final class PrincipalMapping` with `static PrincipalMapping parse(List<String> entries)`, `Optional<Set<String>> forTypeGroup(String name)`, `Optional<Set<String>> forType(String name)`, `Set<String> containerNames()`.

- [ ] **Step 1: Write the failing tests**

```java
@Test void parsesGroupUserAndEveryone()       // "AP=group:AP Clerks|user:tony|everyone" → {"GROUP_AP Clerks","tony","GROUP_EVERYONE"}
@Test void typeEntryIsSeparateFromGroupEntry() // "AP=group:A,AP Invoice=group:B" → forTypeGroup("AP") and forType("AP Invoice") both answer
@Test void malformedEntryNamesIt()            // "AP" / "AP=" / "AP=role:x" → IAE containing the entry
@Test void duplicateContainerIsRejected()
@Test void requiredSettingsNamed()            // each missing required setting → IAE naming it
@Test void defaultsApplied()                  // since 2000-01-01, pageSize 100, sourceId = url host
@Test void pageSizeBelowOneRejected()
@Test void schemaMasksPassword()
```

- [ ] **Step 2–4:** run `mvn -q -f plugins/onbase-connector/pom.xml test` (fail) → implement → (PASS). `createClient` throws `UnsupportedOperationException` until Task 5.
- [ ] **Step 5: Commit** — `git commit -m "feat: onbase connector module, settings and principal mapping"`

---

### Task 2: MockOnBaseServer

**Files:**
- Create: `plugins/onbase-connector/src/test/java/org/hyland/contentlake/connector/onbase/mock/MockOnBaseServer.java` (single dependency-free file, runnable as `java MockOnBaseServer.java`)
- Create: `plugins/onbase-connector/src/test/resources/fixtures/onbase/fixture.json`
- Test: `.../onbase/mock/MockOnBaseServerTest.java`

**Interfaces:**
- Produces: `MockOnBaseServer implements AutoCloseable` with `MockOnBaseServer(Options)`, `String coreUrl()` (`…/onbase/core`), `String authUrl()` (`…/identity`), `List<String> requestLog()`, `void close()`; `record Options(int port, Path fixtures, int tokenCallLimit, Set<String> allowedScopes)`, `defaults(fixtures)` = `(0, fixtures, 0, Set.of("evolution"))`, `withTokenCallLimit(int)`, `withAllowedScopes(Set<String>)`. `main` reads `MOCK_ONBASE_PORT` (default 8097) and `MOCK_ONBASE_FIXTURES`.
- Endpoints: `GET /identity/.well-known/openid-configuration`, `POST /identity/connect/token` (password grant; issues an unsigned JWT with claims `username`, and `group` only when `group` is in the requested and allowed scopes; scope outside `allowedScopes` → 400 `{"error":"invalid_scope"}`), `GET /onbase/core/document-type-groups`, `GET /onbase/core/document-type-groups/{id}/document-types`, `POST /onbase/core/documents/queries` (201 `{"id":…}`; honours `queryType`, `documentDateRangeCollection` inclusive, returns exactly `min(maxResults, matches)` with no truncation flag; type group `TG_DENIED` → 400 `Failed to add DocumentTypeGroup`), `GET /onbase/core/documents/queries/{id}/results` (`items: [{id, displayColumns:[{index:"0", values:[name]}]}]`), `GET /onbase/core/documents/{id}` (`documentDate`, `storedDate`, `typeId`, `name`), `GET /onbase/core/documents/{id}/keywords`, `GET /onbase/core/keyword-types` (`isSecurityMasked`), `GET /onbase/core/documents/{id}/revisions/latest`, `GET /onbase/core/documents/{id}/revisions/{rev}/renditions/default` (`created`, `fileTypeId`), `GET /onbase/core/file-types` (`items: [{id, name, systemName}]`, id 16 = `PDF`), `GET …/renditions/default/content` (bytes + `Content-Type` from fixture, omitted when the fixture says so), `GET /onbase/core/documents/{id}/revisions/{rev}/file` → 404.
- Fixture: type group `TG_TEST` "CL Test" with types `T_RESTRICTED` "CL Test Restricted" and `T_OPEN` "CL Test Open"; `TG_DENIED` "Locked"; 12 documents in `T_OPEN` on one day `2026-10-01`, 3 in `T_RESTRICTED` across days; one document without a revision rendition `created` (falls back to `storedDate`); one rendition without Content-Type; keyword types `Region` (masked) and `Invoice Number`; users `cltest-a` (group `CL Test A`), `cltest-b` (`CL Test B`), service `svc`; all passwords `pass`.

- [ ] **Step 1: Write the failing tests** — one per endpoint behaviour above (`tokenIssuesUsernameClaim`, `groupClaimOnlyWhenScopeAllowed`, `disallowedScopeIsInvalidScope`, `tokenExpiresAfterCallLimit`, `queryReturnsExactlyMaxResultsWithoutFlag`, `dateRangeIsInclusive`, `deniedTypeGroupIs400`, `nameInDisplayColumn`, `fileEndpointIs404`, `renditionWithoutContentType`).
- [ ] **Step 2–4:** run (fail) → implement → (PASS).
- [ ] **Step 5: Commit** — `git commit -m "test: mock OnBase API Server and identity service"`

---

### Task 3: API Server transport

**Files:**
- Create: `.../onbase/OnBaseHttp.java`
- Test: `.../onbase/OnBaseHttpTest.java`

**Interfaces:**
- Produces: `final class OnBaseHttp` with `OnBaseHttp(URI coreUrl, URI authUrl, String clientId, String scope, String username, String password, HttpClient http)`, `JsonNode get(String path)`, `JsonNode post(String path, JsonNode body)` (accepts 200/201), `Download download(String path)` where `record Download(byte[] bytes, String contentType)`; `class OnBaseHttpException extends RuntimeException` with `int status()`.

- [ ] **Step 1: Write the failing tests**

```java
@Test void discoversTokenEndpointAndReusesToken()   // 3 GETs → one token request
@Test void refreshesTokenOnceOn401()                // tokenCallLimit 2, 4 GETs → all succeed, two token requests
@Test void secondConsecutive401Throws()
@Test void downloadKeepsContentType()
@Test void missingContentTypeIsOctetStream()       // Review Focus 4
```

- [ ] **Step 2–4:** run (fail) → implement → (PASS).
- [ ] **Step 5: Commit** — `git commit -m "feat: onbase transport with token refresh"`

---

### Task 4: Document listing by date windows

**Files:**
- Create: `.../onbase/DocumentLister.java`
- Test: `.../onbase/DocumentListerTest.java`

**Interfaces:**
- Produces: `final class DocumentLister` with `DocumentLister(OnBaseHttp http, int pageSize)` and `List<ListedDocument> list(String documentTypeId, LocalDate since, LocalDate until)`; `record ListedDocument(String id, String name)`; `class ListingIncompleteException extends RuntimeException`.

Algorithm: query `[since, until]` with `maxResults = pageSize + 1`. More than `pageSize` back → split the window at its midpoint day into two halves and recurse. A one-day window over `pageSize` → re-query that day with `maxResults = 10001`; more than 10000 → `ListingIncompleteException` naming the type and day. Results de-duplicated by id, ordered by id.

- [ ] **Step 1: Write the failing tests**

```java
@Test void fitsInOneQuery()                       // pageSize 100 → one POST /documents/queries
@Test void splitsWindowsUntilEachFits()           // pageSize 2 on T_RESTRICTED (3 docs on different days) → all 3, more than one query
@Test void singleBusyDayUsesTheLargeCeiling()     // pageSize 5, 12 docs on 2026-10-01 → all 12, a query with maxResults 10001 in the log
@Test void overCeilingThrows()                    // Review Focus 1: a lister constructed with ceiling 10 (package-private constructor) → ListingIncompleteException naming the day
@Test void sendsDocumentDateRange()               // request body has documentDateRangeCollection [{start,end}] in ISO dates
```

- [ ] **Step 2–4:** run (fail) → implement (package-private constructor `DocumentLister(OnBaseHttp, int pageSize, int ceiling)` for the test) → (PASS).
- [ ] **Step 5: Commit** — `git commit -m "feat: onbase listing that splits date windows to defeat the silent cap"`

---

### Task 5: Connector client

**Files:**
- Create: `.../onbase/OnBaseConnectorClient.java`
- Modify: `.../onbase/OnBaseConnectorPlugin.java` (`createClient`)
- Test: `.../onbase/OnBaseConnectorClientTest.java`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces: `OnBaseConnectorClient implements ContentSourceClient`. Node ids `dtg:<id>`, `dt:<id>`, `doc:<id>`. Roots: configured type groups that have a mapping entry, resolved by name at construction; an unknown configured or mapped name → IAE naming it (Review Focus 3); a group answering 400 → WARN and absent from roots (Review Focus 2). `getChildren(dtg)` → its types as folder nodes; `getChildren(dt)` → document nodes from `DocumentLister` for `[since, today]`, paged by `skip`/`max`.

SourceNode values: `name` from the display column; `path` `/<type group>/<type>/<name>`; `mimeType` from the latest revision's default rendition metadata (`fileTypeId`) → `/file-types` name (loaded once) → MIME via a fixed table (`PDF`→`application/pdf`, `Image File Format`→`image/tiff`, `Text Report`→`text/plain`, `MS Word Document`→`application/msword`, `MS Excel Spreadsheet`→`application/vnd.ms-excel`, `Rich Text Format`→`application/rtf`, `HTML`→`text/html`, `JPEG`→`image/jpeg`, `PNG`→`image/png`, `Electronic Mail Message`→`message/rfc822`, else `application/octet-stream`; the host routes text extraction by this value); `modifiedAt` = rendition `created`, else `storedDate` (both local time, treated as UTC); `readPrincipals` = `forType(type)` if present else `forTypeGroup(group)`; `sourceProperties`: `typeGroup`, `documentType`, `documentDate`, and keyword values by keyword type name, excluding types with `isSecurityMasked`. `downloadContent`: `/documents/{id}/revisions/latest` → `…/revisions/{rev}/renditions/default/content`, fresh copy each call.

- [ ] **Step 1: Write the failing tests**

```java
@Test void rootsOnlyForMappedGroups()                 // TG_TEST mapped, TG_DENIED configured → roots ["dtg:TG_TEST"], WARN logged
@Test void unmappedConfiguredGroupIsSkippedAndLogged()
@Test void unknownMappedNameFailsConstruction()       // Review Focus 3
@Test void typeEntryOverridesGroupEntry()
@Test void modifiedAtFallsBackToStoredDate()
@Test void mimeTypeFromRenditionFileType()            // fileTypeId 16 → "application/pdf"; unknown file type name → "application/octet-stream"; /file-types fetched once
@Test void maskedKeywordsAreLeftOut()                 // sourceProperties has "Invoice Number", not "Region"
@Test void downloadUsesLatestRevisionRendition()      // requestLog has …/revisions/latest then …/renditions/default/content
@Test void downloadsAreIndependentCopies()
@Test void pluginCreatesClientFromContext()
```

- [ ] **Step 2–4:** run (fail) → implement → (PASS).
- [ ] **Step 5: Package check** — `mvn -q -f plugins/onbase-connector/pom.xml package && unzip -l plugins/onbase-connector/target/onbase-connector-1.0.0.jar | grep -c 'com/fasterxml'` → tests pass, count > 0.
- [ ] **Step 6: Commit** — `git commit -m "feat: onbase connector client with mapped readers"`

---

### Task 6: Dev-server check (opt-in, read-only)

**Files:**
- Test: `.../onbase/DevServerListingIT.java` (`@EnabledIfEnvironmentVariable(named = "ONBASE_URL", matches = ".+")`)

- [ ] **Step 1: Write the test** — maps type group `Claims` to `group:Dev Check`, lists it, asserts every document has a non-blank name, a `modifiedAt`, and that the first document downloads with a non-empty body. No permission assertions: the OnBase permission fixture needs administrators (see the research doc).
- [ ] **Step 2: Run** with `ONBASE_*` from `apps/workspace-hxp/onbase-server/.env` (mapped to the connector's names; values never echoed). Expected: PASS.
- [ ] **Step 3: Commit** — `git commit -m "test: opt-in OnBase dev-server listing check"`

---

### Task 7: rag-service sign-in and claim groups

**Files:**
- Create: `common/rag-service/src/main/java/org/hyland/contentlake/rag/security/OnBaseDirectory.java`
- Create: `.../rag/security/OnBaseCallerAuthenticator.java`, `.../rag/security/OnBaseGroupResolver.java`
- Modify: `.../rag/security/CallerAuthenticatorOrder.java` (`static final int ONBASE = 60;`)
- Test: `.../rag/security/OnBaseCallerAuthenticatorTest.java`, `OnBaseGroupResolverTest.java` (real `HttpServer`)

**Interfaces:**
- Produces: `OnBaseDirectory(@Value("${rag.security.onbase.auth-url:}") String authUrl, @Value("${rag.security.onbase.client-id:}") String clientId, @Value("${rag.security.onbase.scope:}") String scope, @Value("${rag.security.group-cache.ttl-seconds:300}") long ttlSeconds)` with `Optional<String> authenticate(String username, String password)` (password grant; returns the token's `username` claim; stores the `group` claim values for that username with expiry `ttlSeconds`) and `List<String> groupsFor(String username)` (unexpired stored groups, else empty).
- Produces: `OnBaseCallerAuthenticator` (`@ConditionalOnProperty(name = "rag.security.onbase.enabled", havingValue = "true")`, `id()` `"onbase-password"`, `order()` `ONBASE`, `supports` as CMIS) → `CallerIdentities.builder().add("onbase", username).build()`; `OnBaseGroupResolver` (`sourceType()` `"onbase"`) → `GROUP_<name>` for `groupsFor(username)`.

- [ ] **Step 1: Write the failing tests**

```java
@Test void usernameClaimBecomesOnBaseIdentity()
@Test void wrongPasswordYieldsNull()
@Test void groupsFromClaimArePrefixed()           // scope incl. group → ["GROUP_CL Test A"]
@Test void noGroupClaimMeansNoGroups()            // scope without group → []
@Test void storedGroupsExpire()                   // ttl 1s, after 1.1s → []
@Test void beansAbsentUnlessEnabled()
```

- [ ] **Step 2–4:** run `mvn -q -pl common/rag-service -am test -Dtest='OnBase*Test'` (fail) → implement → (PASS).
- [ ] **Step 5: Commit** — `git commit -m "feat: rag-service OnBase caller sign-in with token group claim"`

---

### Task 8: Documentation

**Files:**
- Create: `plugins/onbase-connector/README.md`
- Modify: `plugins/README.md`, `docs/security-model.md`, `docs/configuration.md` (`rag.security.onbase.enabled|auth-url|client-id|scope`)

- [ ] **Step 1: Write the README** — preview status; **Limitations** (spec 1–10 that apply to OnBase: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10) phrased as what the operator observes; Build and install; Configure it (settings table + mapping format with examples); How content maps; Searching (the `group` scope requirement); Mock server; Real-instance checklist (from the spec).
- [ ] **Step 2: Verify** — every setting in the table matches `OnBaseConnectorPlugin` constants (`grep -o 'onbase\.[a-z-]*'` on both).
- [ ] **Step 3: Commit** — `git commit -m "docs: onbase connector README, security model and configuration"`

---

### Task 9: End-to-end in content-lake-app-deployment

**Files (deployment fork):** `dockerfiles/Dockerfile` (stage `mock-onbase`), `compose.content-lake.yaml` (service `mock-onbase`, profile `onbase-mock`, port `${MOCK_ONBASE_PORT:-8097}`), `test/test-onbase.sh` (modelled on `test/test-sharepoint.sh`), `Makefile` profile comment.

- [ ] **Step 1: Write `test/test-onbase.sh`** — ingest with `CONNECTOR_SOURCE_TYPE=onbase`, `ONBASE_PRINCIPALS='CL Test=group:CL Test A,CL Test Open=group:CL Test A|group:CL Test B'`, rag-service `RAG_SECURITY_ONBASE_*` with scope including `group` (mock allows it); assert `cltest-a` finds a restricted document and `cltest-b` does not; both find an open one; then rerun with the mock's `group` scope disallowed and assert `cltest-b` finds nothing group-mapped (limitation 9).
- [ ] **Step 2: Run** — `docker compose --profile alfresco --profile connector --profile onbase-mock up -d && ./test/test-onbase.sh`. Expected: PASS; if the base stack is unavailable locally, record the run as pending in the PR description.
- [ ] **Step 3: Commit** — `git commit -m "test: onbase connector end-to-end against a mock API Server"`

---

### Task 10: Wrap-up

- [ ] **Step 1:** `mvn -q -f plugins/onbase-connector/pom.xml verify && mvn -q -pl common/rag-service -am test` → PASS.
- [ ] **Step 2:** Push both fork branches. No upstream PR or issue without the user's go-ahead.
