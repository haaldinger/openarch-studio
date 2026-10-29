# Perceptive Content connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Content Lake plugin that ingests Perceptive Content documents with readers computed from Perceptive's own drawer and document type privileges, plus the rag-service sign-in and group lookup that make those readers match callers.

**Architecture:** A shaded plugin jar in `plugins/perceptive-connector/` (built only against `content-lake-spi`) talks to Integration Server over one reused session, lists documents through capped view searches that it splits until complete, and resolves deny-wins privileges itself before emitting readers. Two `@ConditionalOnProperty` beans in `common/rag-service` sign callers in and resolve their groups. A dependency-free `MockPerceptiveServer` reproduces the API's traps for unit and end-to-end tests.

**Tech Stack:** Java (compile `release 21`, build with JDK 25), Maven, JDK `HttpClient`, Jackson 2.22.0 (shaded), JUnit 5, AssertJ, Mockito; Spring Boot in rag-service; bash + docker compose for end-to-end.

**Spec:** `docs/superpowers/specs/2026-10-28-perceptive-onbase-connectors-design.md` (Perceptive parts). Research and dev-server fixture: `docs/research/2026-10-28-perceptive-onbase-connectors.md`.

## Global Constraints

- Repositories: fork `AlfrescoLabs/content-lake-app` and `AlfrescoLabs/content-lake-app-deployment` to `haaldinger`; one branch `feat/perceptive-onbase-connectors` in each.
- Toolchain: `export JAVA_HOME=$(brew --prefix openjdk@25)` before every Maven command.
- Plugin coordinates `org.hyland.contentlake:perceptive-connector:1.0.0`, package `org.hyland.contentlake.connector.perceptive`, `sourceType` = `perceptive`.
- Plugin pom mirrors `plugins/sharepoint-connector/pom.xml`: `content-lake-spi` `1.0.0-SNAPSHOT`, `spring-core` `7.0.8` and `slf4j-api` `provided`; `jackson-databind` `2.22.0` shaded; `maven.compiler.release` `21`. Never added to the root POM.
- Setting names `perceptive.<name>`; env vars upper-case with `.`/`-` → `_`.
- Nothing is ever written to Perceptive. Only GET, the session calls, and `POST /v6/view/{id}/result`.
- Fail closed: a document whose readers cannot be determined, or whose reader set is empty, is skipped and logged at WARN with drawer and reason; never ingested readable by everyone.
- Principals: groups `GROUP_<groupId>`, users the Perceptive username exactly as `/v2/user` reports it.
- Commits: `type: short description` (`feat:`, `test:`, `docs:`).

## Review Focus

1. **Drawer name containing `'`** → VSL injection/breakage; expected: startup fails naming the drawer. Test in Task 1.
2. **Document type from another department** (privilege call answers 400) → expected: that document is undeterminable and skipped, the rest of the drawer continues. Test in Task 4.
3. **Session expires mid-walk** (401 after N calls) → expected: one re-login, walk continues; a second consecutive 401 fails the call. Test in Task 3.
4. **Granted group with zero members after deny expansion** → readers empty → expected: document skipped, not ingested readable by nobody/everyone. Test in Task 4.
5. **View search that never stops reporting more** (`hasMore` even at a 64-character prefix) → expected: `ListingIncompleteException` naming the drawer; nothing from that drawer is ingested. Test in Task 5.

---

### Task 0: Forks, toolchain, upstream issue draft

**Files:**
- Create: `docs/superpowers/upstream-issue-perceptive-onbase.md` (in the Studio repo, next to the spec)

- [ ] **Step 1: Fork and clone**

```bash
gh repo fork AlfrescoLabs/content-lake-app --clone=false
gh repo fork AlfrescoLabs/content-lake-app-deployment --clone=false
cd "/Users/heath.aldinger/Desktop/CIC DEV APPS/Apps"
git clone https://github.com/haaldinger/content-lake-app.git
git clone https://github.com/haaldinger/content-lake-app-deployment.git
(cd content-lake-app && git switch -c feat/perceptive-onbase-connectors)
(cd content-lake-app-deployment && git switch -c feat/perceptive-onbase-connectors)
```

- [ ] **Step 2: Install the SPI**

Run: `cd content-lake-app && export JAVA_HOME=$(brew --prefix openjdk@25) && mvn -q -pl common/content-lake-spi -am install -DskipTests && mvn -q -f plugins/cmis-connector/pom.xml verify`
Expected: both succeed (proves the toolchain builds an existing plugin).

- [ ] **Step 3: Draft the upstream issue**

Write the issue body from the spec's "Upstream issue" section: research summary, design, all 14 limitations, and the two questions (OnBase mapping acceptable? deny resolution in the connector acceptable given `cin_deny` is not enforced?). Do not post it: posting to AlfrescoLabs is a public action and needs the user's go-ahead.

- [ ] **Step 4: Commit (Studio repo)**

```bash
git add docs/superpowers/upstream-issue-perceptive-onbase.md
git commit -m "docs: draft upstream issue for Perceptive and OnBase connectors"
```

---

### Task 1: Module, settings and schema

**Files:**
- Create: `plugins/perceptive-connector/pom.xml`
- Create: `plugins/perceptive-connector/src/main/java/org/hyland/contentlake/connector/perceptive/PerceptiveConnectorPlugin.java`
- Create: `plugins/perceptive-connector/src/main/java/org/hyland/contentlake/connector/perceptive/PerceptiveSettings.java`
- Create: `plugins/perceptive-connector/src/main/resources/META-INF/services/org.hyland.contentlake.spi.ConnectorPlugin` (one line: `org.hyland.contentlake.connector.perceptive.PerceptiveConnectorPlugin`)
- Test: `plugins/perceptive-connector/src/test/java/org/hyland/contentlake/connector/perceptive/PerceptiveSettingsTest.java`

**Interfaces:**
- Produces: `PerceptiveConnectorPlugin` constants `SOURCE_TYPE = "perceptive"`, `URL_SETTING`, `USERNAME_SETTING`, `PASSWORD_SETTING`, `SOURCE_ID_SETTING`, `DRAWERS_SETTING = "perceptive.drawers"`, `VIEWS_SETTING = "perceptive.views"`, `UNREADABLE_GROUPS_SETTING = "perceptive.unreadable-groups"`.
- Produces: `record PerceptiveSettings(URI url, String username, String password, String sourceId, List<String> drawers, Map<String, String> viewByDrawer, UnreadableGroups unreadableGroups)` with `static PerceptiveSettings from(ConnectorContext ctx)`, `String viewFor(String drawer)` (drawer entry, else `*` entry, else `IllegalArgumentException`), and `enum UnreadableGroups { SKIP_DRAWER, IGNORE }`.

- [ ] **Step 1: Write the failing tests**

```java
@Test void requiredSettingsMissingNamesTheSetting()      // url/username/password/drawers/views blank → IAE message contains "perceptive.url" etc.
@Test void sourceIdDefaultsToUrlHost()                  // url https://pc.example:8500/integrationserver → sourceId "pc.example"
@Test void viewsParseDrawerEqualsViewWithWildcard()     // "HR=HR Docs,*=All Docs" → viewFor("HR")=="HR Docs", viewFor("AP")=="All Docs"
@Test void drawerWithoutViewFailsWhenNoWildcard()       // drawers "HR,AP", views "HR=HR Docs" → IAE mentions "AP"
@Test void drawerNameWithQuoteIsRejected()              // drawer "O'Brien" → IAE mentions "O'Brien" (VSL safety)
@Test void unreadableGroupsDefaultsToSkipDrawer()       // unset → SKIP_DRAWER; "ignore" → IGNORE; "bogus" → IAE
@Test void schemaMasksPasswordAndListsEverySetting()    // plugin.schema().fields() names == the 7 settings; password field secret
```

- [ ] **Step 2: Run to verify failure**

Run: `mvn -q -f plugins/perceptive-connector/pom.xml test -Dtest=PerceptiveSettingsTest`
Expected: compilation failure (classes missing).

- [ ] **Step 3: Implement**

Copy the pom from `plugins/sharepoint-connector/pom.xml`, drop `msal4j`, rename coordinates. Schema via `ConnectorSchema.builder(SOURCE_TYPE)`: `required(URL_SETTING, URL, …)`, `secret(USERNAME_SETTING, …, true)`, `secret(PASSWORD_SETTING, …, true)`, `optional(SOURCE_ID_SETTING, STRING, …)`, `required(DRAWERS_SETTING, LIST, …)`, `required(VIEWS_SETTING, LIST, …)`, `enumeration(UNREADABLE_GROUPS_SETTING, …, false, List.of("skip-drawer", "ignore"))`. `createClient` is added in Task 6; throw `UnsupportedOperationException` until then.

- [ ] **Step 4: Run tests**

Run: `mvn -q -f plugins/perceptive-connector/pom.xml test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/perceptive-connector
git commit -m "feat: perceptive connector module, settings and schema"
```

---

### Task 2: MockPerceptiveServer and fixtures

**Files:**
- Create: `plugins/perceptive-connector/src/test/java/org/hyland/contentlake/connector/perceptive/mock/MockPerceptiveServer.java` (single file, JDK `com.sun.net.httpserver` + hand-rolled JSON writing; no dependencies, runnable as `java MockPerceptiveServer.java`)
- Create: `plugins/perceptive-connector/src/test/resources/fixtures/perceptive/fixture.json`
- Test: `plugins/perceptive-connector/src/test/java/org/hyland/contentlake/connector/perceptive/mock/MockPerceptiveServerTest.java`

**Interfaces:**
- Produces: `MockPerceptiveServer implements AutoCloseable`, `MockPerceptiveServer(Options)`, `String baseUrl()` (ends in `/integrationserver`), `int chargedCalls()`, `int freeCalls()`, `List<String> requestLog()`, `void setPassword(String userName, String password)`, `void close()`; `record Options(int port, Path fixtures, int listingCap, int sessionCallLimit)` with `static Options defaults(Path fixtures)` = `(0, fixtures, 500, 0)` and `withListingCap(int)`, `withSessionCallLimit(int)` (0 = never expire). `main(String[])` reads `MOCK_PERCEPTIVE_PORT` (default 8098) and `MOCK_PERCEPTIVE_FIXTURES`.
- Endpoints (response shapes copied from the research probes): `GET|DELETE /v1/connection`, `GET /v2/connection`, `GET /v1/drawer`, `GET /v1/drawer/{id}`, `GET /v1/department`, `GET /v1/userGroup?departmentId=`, `GET /v2/userGroup/{id}`, `GET /v2/user`, `GET /v1/user/{id}/group`, `GET /v2/userGroup/{id}/privilege`, `GET /v2/user/{id}/privilege`, `GET /v1/view?category=DOCUMENT`, `POST /v6/view/{id}/result?category=DOCUMENT` (result rows carry columns `Document ID` and `Drawer`), `GET /v7/document/{id}`, `GET /v1/document/{id}/page/{pageId}/file`.
- Fixture ids used by later tasks: users `cltest-a` (`U_A`), `cltest-b` (`U_B`), `cltest-c` (`U_C`), service `svc` (`U_SVC`, password `svc-pass`; test users' password `pass`); groups `G_A` (`CL Test A`: U_A, U_C) and `G_B` (`CL Test B`: U_B) in department `D_GT`, plus `G_OTHER` in department `D_OTHER` (answers 400 from `D_GT`); drawers `DR_RESTRICTED` "GT-Human Resources", `DR_OPEN` "GT-Financial Aid", `DR_TYPEONLY` "GT-UG Registrar"; types `T_NORMAL`, `T_DENY_A`, `T_GRANT_B`, `T_FOREIGN` (privilege calls answer 400); view `V_ALL` "CL Test Docs". Documents and privileges exactly as the research doc's fixture table, plus `DOC_FOREIGN` (in `DR_OPEN`, type `T_FOREIGN`). The symbolic names above are for the plan; real ids in the fixture use Perceptive's format `[0-9A-Z_]{23}` (e.g. `321ZT01_000000000000001`), because the connector's listing split depends on that alphabet.

- [ ] **Step 1: Write the failing tests**

```java
@Test void connectionReturnsSessionHashAndV2ReportsUser()    // GET /v1/connection with X-IntegrationServer-Username/Password → header X-IntegrationServer-Session-Hash; /v2/connection → {"userId":"U_SVC","userName":"svc"}
@Test void wrongPasswordIs401()
@Test void sessionExpiresAfterCallLimit()                    // withSessionCallLimit(3): 4th call with same hash → 401
@Test void drawerListingStopsAtCapWithoutPaging()            // withListingCap(2): /v1/drawer/DR_OPEN containedDocuments.size()==2 even with ?start=2
@Test void viewResultStopsAtCapAndSetsHasMore()              // POST /v6/view/V_ALL/result?category=DOCUMENT {"vslText":"[drawer] = 'GT-Financial Aid'"} with cap 2 → 2 rows, hasMore=true
@Test void viewHonoursDocIdRange()                           // vslText "... AND [docId] >= 'A' AND [docId] < 'M'" filters by String.compareTo
@Test void privilegeWithoutQueryParamIsEmpty()               // /v2/userGroup/G_A/privilege → {"privilegeSets":[]}
@Test void privilegeForDrawerReturnsDocView()                // ?drawerId=DR_RESTRICTED → DOC_VIEW GRANTED
@Test void groupFromOtherDepartmentIs400()                   // /v2/userGroup/G_OTHER/privilege?drawerId=… → 400 with "not owned by the current department"
@Test void foreignDocumentTypeIs400()                        // ?documentTypeId=T_FOREIGN → 400
@Test void userGroupsInOneCall()                             // /v1/user/U_C/group → groups [G_A]
@Test void pageFileIsOctetStream()                           // /v1/document/{id}/page/{pid}/file → 200, Content-Type application/octet-stream
@Test void freeAndChargedCallsAreCounted()                   // connection, /v2/user, /v2/userGroup/*, privileges are free; drawer, view, document, page calls charged
```

- [ ] **Step 2: Run to verify failure** — `mvn -q -f plugins/perceptive-connector/pom.xml test -Dtest=MockPerceptiveServerTest` → compilation failure.

- [ ] **Step 3: Implement the mock and fixture**

VSL support is limited to conjunctions of `[drawer] = '<s>'`, `[docId] >= '<s>'`, `[docId] < '<s>'`; anything else → 400 "The search parameters are invalid." Results ordered by insertion, not by id (the real server's order is unknown, so the connector must not rely on it). Free-call set copied from Hyland's licensing page: `/v1/connection`, `/v2/connection`, `/v2/user`, `/v2/user/{id}/privilege`, `/v2/userGroup/{id}`, `/v2/userGroup/{id}/privilege`, `/v1/serverInfo`.

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "test: mock Perceptive Integration Server with listing caps, privileges and licensing"`

---

### Task 3: Integration Server transport

**Files:**
- Create: `.../perceptive/PerceptiveHttp.java`
- Test: `.../perceptive/PerceptiveHttpTest.java`

**Interfaces:**
- Consumes: `PerceptiveSettings` (Task 1), `MockPerceptiveServer` (Task 2).
- Produces: `final class PerceptiveHttp implements AutoCloseable` with `PerceptiveHttp(URI baseUrl, String username, String password, HttpClient http)`, `JsonNode get(String path)`, `JsonNode post(String path, JsonNode body)`, `byte[] download(String path)`, `int chargedCalls()`, `void close()` (DELETE `/v1/connection` once); `class PerceptiveHttpException extends RuntimeException` with `int status()` and `String serverMessage()` (from `X-IntegrationServer-Error-Message` or body).

- [ ] **Step 1: Write the failing tests**

```java
@Test void reusesOneSessionAcrossCalls()               // 5 GETs → mock requestLog shows exactly one /v1/connection
@Test void reLogsInOnceOn401ThenSucceeds()             // sessionCallLimit 2, 4 GETs → all succeed, two /v1/connection
@Test void secondConsecutive401Throws()                // mock with wrong password after first login → PerceptiveHttpException status 401
@Test void non2xxCarriesServerMessage()                // G_OTHER privilege → status 400, serverMessage contains "current department"
@Test void closeDeletesSessionOnce()                   // close() twice → one DELETE /v1/connection
@Test void chargedCallsMatchMock()                     // after a mix of calls, http.chargedCalls()==mock.chargedCalls()
```

- [ ] **Step 2–4:** run (fail) → implement (calls serialised with a lock, since Integration Server runs one call at a time per session; `Accept: application/json`) → run (PASS).

- [ ] **Step 5: Commit** — `git commit -m "feat: perceptive session transport with single re-login"`

---

### Task 4: Reader rules and privilege index

**Files:**
- Create: `.../perceptive/ReaderRules.java` (pure)
- Create: `.../perceptive/PrivilegeIndex.java`
- Test: `.../perceptive/ReaderRulesTest.java`, `.../perceptive/PrivilegeIndexTest.java`

**Interfaces:**
- Produces: `enum Setting { GRANTED, DENIED, UNSET }`; `record Readers(Set<String> read, Set<String> deny, Optional<String> undeterminedReason)`; `final class ReaderRules` with `static Readers resolve(Map<String, Setting> groupDrawer, Map<String, Setting> groupType, Map<String, Setting> userDrawer, Map<String, Setting> userType, Map<String, Set<String>> membersByGroup, Map<String, String> usernameById)` (maps keyed by group or user id).
- Produces: `final class PrivilegeIndex` with `PrivilegeIndex(PerceptiveHttp http, PerceptiveSettings.UnreadableGroups mode)` and `Readers readersFor(String drawerId, String documentTypeId)`; loads groups (`/v1/department`, `/v1/userGroup?departmentId=`, members from `/v2/userGroup/{id}`) and users (`/v2/user`) once, caches each privilege lookup per `(principal, drawerId|typeId)`.

Rules `resolve` must implement (from the spec, verbatim intent):
1. Per object (drawer, type): a user's own non-`UNSET` setting wins; else across the user's groups any `DENIED` → `DENIED`, else any `GRANTED` → `GRANTED`, else `UNSET`.
2. A user reads iff neither object is `DENIED` and at least one is `GRANTED`.
3. If no `DENIED` anywhere and no user-level setting on either object: `read` = `GROUP_<id>` for each group `GRANTED` on either object (and not denied on the other) — otherwise `read` = usernames passing rule 2.
4. `deny` = `GROUP_<id>` / usernames with `DENIED` (diagnostics only).

- [ ] **Step 1: Write the failing tests**

```java
// ReaderRulesTest — the research fixture table, one test each:
@Test void restrictedDrawerWithUserDenyExpandsToUsers()      // drawer A=GRANTED, user U_C=DENIED → read == {"cltest-a"}, deny == {"cltest-c"}
@Test void openDrawerWithoutExceptionsEmitsGroups()           // A,B GRANTED, type NORMAL all UNSET → read == {"GROUP_G_A","GROUP_G_B"}
@Test void typeDenyBeatsDrawerGrant()                         // drawer A,B GRANTED, type A=DENIED → read == {"cltest-b"}
@Test void typeGrantAloneIsEnough()                           // drawer UNSET, type B=GRANTED → read == {"GROUP_G_B"}
@Test void nothingGrantedReadsNobody()                        // all UNSET → read == {}
@Test void userGrantBeatsGroupDeny()                          // group DENIED, user GRANTED → user reads
@Test void deniedMemberOfOnlyGrantedGroupLeavesEmptyRead()    // Review Focus 4: sole member denied → read == {}
// PrivilegeIndexTest — against the mock:
@Test void foreignTypeIsUndetermined()                        // Review Focus 2: readersFor(DR_OPEN, T_FOREIGN).undeterminedReason() present, mentions type
@Test void unreadableGroupSkipsDrawerByDefault()              // G_OTHER present, SKIP_DRAWER → undeterminedReason present and names G_OTHER's group name
@Test void unreadableGroupIgnoredWhenConfigured()             // IGNORE → readers computed without G_OTHER
@Test void privilegeCallsAreFreeAndCached()                   // readersFor same pair twice → mock.chargedCalls() unchanged, privilege calls not repeated
```

- [ ] **Step 2–4:** run (fail) → implement → run (PASS).

- [ ] **Step 5: Commit** — `git commit -m "feat: perceptive readers from drawer and document type privileges"`

---

### Task 5: Complete drawer listing through split view searches

**Files:**
- Create: `.../perceptive/DrawerLister.java`
- Test: `.../perceptive/DrawerListerTest.java`

**Interfaces:**
- Consumes: `PerceptiveHttp`.
- Produces: `final class DrawerLister` with `DrawerLister(PerceptiveHttp http)` and `List<String> documentIds(String drawerName, String viewId)` (sorted, distinct); `class ListingIncompleteException extends RuntimeException`.

Split algorithm (the part the signature does not determine): ids use the alphabet `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_` (sorted by `String.compareTo`). A part is a prefix `p`; its VSL is `[drawer] = '<name>'` plus, for non-empty `p`, `AND [docId] >= '<p>' AND [docId] < '<next(p)>'`, where `next(p)` is `p` with its last character replaced by the following alphabet character (dropping trailing `_` positions first and carrying left; the all-`_` prefix has no upper bound). Run `p = ""`; when a part answers `hasMore=true`, replace it with the parts `p + c` for every alphabet character `c`; collect ids from parts answering `hasMore=false`. A part whose prefix reaches 64 characters and still answers `hasMore=true` throws `ListingIncompleteException` naming the drawer and prefix.

- [ ] **Step 1: Write the failing tests**

```java
@Test void smallDrawerNeedsOneQuery()                 // cap 500 → one view call, all ids
@Test void cappedDrawerIsSplitUntilComplete()         // cap 2, 7 docs → returns all 7, distinct, sorted
@Test void unsplittableRangeThrows()                  // Review Focus 5: withListingCap(0) (every non-empty part reports hasMore) → ListingIncompleteException mentioning the drawer
@Test void prefixBoundsUseNextCharacter()             // parts for prefix "32" send "[docId] >= '32' AND [docId] < '33'"; prefix "3_" sends upper bound '4'
@Test void vslQuotesTheDrawerName()                   // requestLog contains "[drawer] = 'GT-Financial Aid'"
```

- [ ] **Step 2–4:** run (fail) → implement → run (PASS).

- [ ] **Step 5: Commit** — `git commit -m "feat: perceptive drawer listing that splits capped view searches"`

---

### Task 6: Connector client

**Files:**
- Create: `.../perceptive/PerceptiveConnectorClient.java`
- Modify: `.../perceptive/PerceptiveConnectorPlugin.java` (`createClient`)
- Test: `.../perceptive/PerceptiveConnectorClientTest.java`

**Interfaces:**
- Consumes: Tasks 1, 3, 4, 5.
- Produces: `PerceptiveConnectorClient implements ContentSourceClient, AutoCloseable`. Node ids: drawers `drawer:<drawerId>`, pages `page:<docId>:<pageId>`. `getChildren("drawer:…", skip, max)` returns page nodes for the documents `DrawerLister` found, in id order, skipping undetermined/empty-reader documents (WARN log with drawer, document id, reason). Folders are not modelled.

SourceNode values (spec "How each source maps to the SPI"):
- `name`: one page → document name; several → `<name> — page n of N`; when the document name equals its id → `<documentType> <field1> <field2>` (trimmed).
- `path`: `/<drawer name>/<name>`; `mimeType` from the page file extension (`pdf`→`application/pdf`, `tif`/`tiff`→`image/tiff`, `jpg`/`jpeg`→`image/jpeg`, `png`→`image/png`, `txt`→`text/plain`, `doc`→`application/msword`, `docx`→OOXML word, `msg`→`application/vnd.ms-outlook`, else `application/octet-stream`).
- `modifiedAt`: `info.modificationUserInfo.time`, else `info.creationUserInfo.time` (epoch ms, UTC).
- `sourceProperties`: `drawer`, `documentType`, `field1`–`field5`, `documentId`, `pageNumber`, `pageCount`.
- `downloadContent` returns a `ByteArrayResource` over a fresh copy of the page bytes; `getContent` the bytes.
- `authState()`: `SourceAuthState.signedInAs("password", username, <time of last successful sign-in>, …)` after a successful call; `SourceAuthState.needsSignIn("password", username, "Check perceptive.username and perceptive.password", …)` after `PerceptiveHttp` gives up on a 401 (fill the remaining arguments per the record).
- After each drawer is listed and mapped, log at INFO: drawer, documents ingested, documents skipped, and `http.chargedCalls()` so far; expose `long chargedCalls()` on the client.

- [ ] **Step 1: Write the failing tests**

```java
@Test void rootsAreConfiguredDrawers()                       // getRootNodeIds() == ["drawer:DR_RESTRICTED", …] in configured order; unknown drawer name → IAE at construction
@Test void multiPageDocumentBecomesOneNodePerPage()          // "cltest restricted 2" → two nodes "… — page 1 of 2", "… — page 2 of 2"
@Test void nodesCarryComputedReaders()                       // restricted 1 → readPrincipals {"cltest-a"}; open 1 → {"GROUP_G_A","GROUP_G_B"}
@Test void undeterminedDocumentIsSkippedNotOpened()          // DOC_FOREIGN absent from getChildren(DR_OPEN)
@Test void typeOnlyNormalDocumentIsSkipped()                 // empty readers → absent
@Test void idOnlyNameFallsBackToTypeAndKeys()
@Test void modifiedAtFallsBackToCreation()
@Test void downloadReturnsIndependentCopies()                // two downloads, mutate first array → second unchanged
@Test void skipAndMaxPageThroughNodes()                      // skip 1 max 1 → second node only
@Test void authStateReportsSignedInThenNeedsSignIn()         // after a call: signed in as "svc"; after mock password changes and a 401 persists: needs sign-in
@Test void chargedCallsAreExposed()                          // after listing DR_OPEN, client.chargedCalls() == mock.chargedCalls()
@Test void pluginCreatesClientFromContext()
```

- [ ] **Step 2–4:** run (fail) → implement → run (PASS).

- [ ] **Step 5: Run the whole module and package**

Run: `mvn -q -f plugins/perceptive-connector/pom.xml package && unzip -l plugins/perceptive-connector/target/perceptive-connector-1.0.0.jar | grep -c 'com/fasterxml'`
Expected: tests pass; Jackson is shaded into the jar (count > 0); no `org/hyland/contentlake/spi` classes in it.

- [ ] **Step 6: Commit** — `git commit -m "feat: perceptive connector client with computed readers"`

---

### Task 7: Dev-server check (opt-in)

**Files:**
- Test: `.../perceptive/DevServerReadersIT.java` (`@EnabledIfEnvironmentVariable(named = "PERCEPTIVE_URL", matches = ".+")`)

**Interfaces:**
- Consumes: `PerceptiveHttp`, `PrivilegeIndex`, `DrawerLister`, `PerceptiveConnectorClient`.

- [ ] **Step 1: Write the test** — builds a client for drawers `GT-Human Resources,GT-Financial Aid,GT-UG Registrar` and asserts the research fixture table: `cltest restricted 1/2` → `{"cltest-a"}`; `cltest open 1` → the two `CL Test` groups; `cltest open denied-type` → `{"cltest-b"}`; `cltest typeonly granted` → the `CL Test B` group; `cltest typeonly normal` absent. Prints charged calls.
- [ ] **Step 2: Run** — `PERCEPTIVE_URL=… PERCEPTIVE_USERNAME=… PERCEPTIVE_PASSWORD=… PERCEPTIVE_VIEWS='*=<view covering the GT drawers>' mvn -q -f plugins/perceptive-connector/pom.xml verify -Dtest=DevServerReadersIT` with values from `cic-perceptive-widget/perceptive-6itbo/.env.perceptive.local` (never echoed). Expected: PASS. If the type-only expectation fails, record it in the research doc as the answer to the spec's first open question and adjust `ReaderRules` rule 2 with a test.
- [ ] **Step 3: Commit** — `git commit -m "test: opt-in check of computed readers against a Perceptive dev server"`

---

### Task 8: rag-service sign-in and groups

**Files:**
- Create: `common/rag-service/src/main/java/org/hyland/contentlake/rag/security/PerceptiveDirectory.java`
- Create: `.../rag/security/PerceptiveCallerAuthenticator.java`
- Create: `.../rag/security/PerceptiveGroupResolver.java`
- Modify: `.../rag/security/CallerAuthenticatorOrder.java` (add `static final int PERCEPTIVE = 50;`)
- Test: `common/rag-service/src/test/java/org/hyland/contentlake/rag/security/PerceptiveCallerAuthenticatorTest.java`, `PerceptiveGroupResolverTest.java` (real `HttpServer`, like `CmisCallerAuthenticatorTest`)

**Interfaces:**
- Produces: `PerceptiveDirectory(@Value("${rag.security.perceptive.url:}") String url, @Value("${rag.security.perceptive.username:}") String serviceUser, @Value("${rag.security.perceptive.password:}") String servicePassword)` with `Optional<String> authenticate(String username, String password)` (GET `/v2/connection` with the caller's credentials, returns `userName`, then DELETE `/v1/connection`) and `List<String> groupIds(String username)` (service session: `/v2/user` name→id map cached for the group-cache TTL, then `/v1/user/{id}/group`).
- Produces: `PerceptiveCallerAuthenticator` (`@ConditionalOnProperty(name = "rag.security.perceptive.enabled", havingValue = "true")`, `id()` `"perceptive-password"`, `order()` `CallerAuthenticatorOrder.PERCEPTIVE`, `supports` exactly as CMIS: not reserved, non-blank password and principal) returning `CallerIdentities.builder().add("perceptive", userName).build()`.
- Produces: `PerceptiveGroupResolver implements SourceGroupResolver` (same condition), `sourceType()` `"perceptive"`, `resolveGroups(username)` → `GROUP_<groupId>` list.

- [ ] **Step 1: Write the failing tests**

```java
@Test void validCredentialsYieldPerceptiveScopedIdentity()   // usernameFor("perceptive") == "cltest-a"
@Test void wrongPasswordYieldsNull()
@Test void reservedAndBlankPasswordAreNotSupported()
@Test void sessionIsClosedAfterCheck()                       // server saw DELETE /v1/connection
@Test void groupsAreGroupPrefixedIds()                       // resolveGroups("cltest-c") == ["GROUP_G_A"]  (same literal format as the connector)
@Test void unknownUserHasNoGroups()
@Test void beansAbsentUnlessEnabled()                        // ApplicationContextRunner without the property → no PerceptiveCallerAuthenticator bean
```

- [ ] **Step 2–4:** run `mvn -q -pl common/rag-service -am test -Dtest='Perceptive*Test'` (fail) → implement → (PASS).

- [ ] **Step 5: Commit** — `git commit -m "feat: rag-service Perceptive caller sign-in and group resolution"`

---

### Task 9: Documentation

**Files:**
- Create: `plugins/perceptive-connector/README.md`
- Modify: `plugins/README.md` (connector table row, marked preview)
- Modify: `docs/security-model.md` (section: sources whose readers are resolved by the connector or configured)
- Modify: `docs/configuration.md` (`rag.security.perceptive.enabled|url|username|password`)

- [ ] **Step 1: Write the README** — sections: what it does (preview), **Limitations** (spec limitations 2, 3, 5, 6, 7, 8, 11, 12, 13, 14, each phrased as what the operator will observe), Build and install, Configure it (settings table with env names), How content and readers map (the reader rules), Searching (rag-service properties), Mock server (`java MockPerceptiveServer.java`), Real-instance checklist (spec Testing section; ordinary non-manager test users).
- [ ] **Step 2: Verify links and names** — `grep -n 'perceptive\.' plugins/perceptive-connector/README.md` lists exactly the 7 settings; every limitation number cited exists in the spec.
- [ ] **Step 3: Commit** — `git commit -m "docs: perceptive connector README, security model and configuration"`

---

### Task 10: End-to-end in content-lake-app-deployment

**Files (deployment fork):**
- Modify: `dockerfiles/Dockerfile` (stage `mock-perceptive` from `eclipse-temurin:25-jdk-alpine`, copying `plugins/perceptive-connector/src/test/java/.../mock/MockPerceptiveServer.java` and the fixtures, `ENTRYPOINT ["java", ".../MockPerceptiveServer.java"]`, like `mock-graph`)
- Modify: `compose.content-lake.yaml` (service `mock-perceptive`, profile `perceptive-mock`, port `${MOCK_PERCEPTIVE_PORT:-8098}`, env `MOCK_PERCEPTIVE_PORT`, `MOCK_PERCEPTIVE_FIXTURES`)
- Create: `test/test-perceptive.sh` (modelled on `test/test-sharepoint.sh`)
- Modify: `Makefile` comment block listing opt-in profiles

- [ ] **Step 1: Write `test/test-perceptive.sh`** — prerequisites and usage header like `test-sharepoint.sh`; configures `plugin-batch-ingester` with `CONNECTOR_SOURCE_TYPE=perceptive`, `PERCEPTIVE_URL=http://mock-perceptive:8098/integrationserver`, rag-service `RAG_SECURITY_PERCEPTIVE_*`; ingests; then asserts as each fixture user through the RAG API: `cltest-a` finds "Restricted drawer document one", `cltest-b` and `cltest-c` do not; `cltest-b` finds "document type denied to group A", `cltest-a` does not; nobody finds "No drawer grant and no type grant"; `DOC_FOREIGN` text is found by nobody.
- [ ] **Step 2: Run** — `docker compose --profile alfresco --profile connector --profile perceptive-mock up -d` then `./test/test-perceptive.sh`. Expected: all assertions pass. Needs the base stack and AI backend (see the script header); if unavailable locally, record that the run is pending in the PR description rather than claiming it passed.
- [ ] **Step 3: Commit (deployment fork)** — `git commit -m "test: perceptive connector end-to-end against a mock Integration Server"`

---

### Task 11: Branch wrap-up

- [ ] **Step 1:** `mvn -q -f plugins/perceptive-connector/pom.xml verify && mvn -q -pl common/rag-service -am test` → PASS.
- [ ] **Step 2:** Push both fork branches. Do not open upstream PRs or post the issue without the user's go-ahead.
