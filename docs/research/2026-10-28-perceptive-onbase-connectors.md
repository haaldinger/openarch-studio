# Perceptive Content and OnBase connectors: API spike and limitations

Date: 2026-10-28 · Status: research input for the connector design

## Question

Can connectors for Perceptive Content and OnBase be built on the content-lake-app connector SPI
(`content-lake-spi`, the same plugin mechanism as the CMIS, SharePoint and filesystem connectors),
and can each document's **read principals** be taken from the source? The SPI's rule is to fail
closed: a document whose permissions cannot be read must be left out, never ingested as readable by
everyone.

## Method

Read-only calls on 2026-10-28 against one Perceptive Content 7.13 demo server (Integration Server REST)
and one OnBase demo server (Hyland API Server, `onbase/core`), with existing demo credentials. Only
`GET` requests, Perceptive's session login/logout, and read-only queries (a Perceptive view result and
an OnBase document query). Nothing was created, changed or deleted.

## Findings

| | Perceptive Content (Integration Server 7.13) | OnBase (API Server, core) |
|---|---|---|
| Authentication | Session hash: `GET /v1/connection` with username/password headers, `DELETE /v1/connection` to end it | OAuth 2 password grant at the IdentityService token endpoint; bearer token |
| Walk content | Drawers (`/v1/drawer`), each listing contained folders and documents (`/v1/drawer/{id}`); document pages are the files (`/v1/document/{id}/page`, `/page/{pageId}/file`) | Document type groups and document types (`/document-type-groups`, `/document-types`); documents found through queries (`POST /documents/queries`, then `/results`) |
| Metadata and change time | `/v7/document/{id}`: document type, drawer, index fields `field1`–`field5`, creation and modification user and time | Keyword types (`/keyword-types`, with a per-type `isSecurityMasked` flag); document keywords per document. `/documents/{id}` has only `documentDate` (business date) and `storedDate`; no modified time. The latest revision (`/documents/{id}/revisions/latest`) and its rendition's `created` time are the closest change signal |
| File content | Page files (above), type from the file extension | `GET /documents/{id}/revisions/{revisionId}/renditions/default/content` returns the native file with its content type (a PDF in the sample). `/revisions/latest/file`, `/documents/{id}/content` and `/file` return 404 |
| Users and groups | Users (`/v2/user`); departments (`/v1/department`); user groups per department (`/v1/userGroup?departmentId=`) with members (`/v1/userGroup/{id}`) | None found: `/users`, `/user-groups`, `/groups` return 404 |
| Who can read a document | Not per document, but per drawer and per document type: `GET /v2/userGroup/{id}/privilege?drawerId=…` and `?documentTypeId=…` (and the same on `/v2/user/{id}/privilege`) return each privilege as `GRANTED`, `DENIED` or `UNSET`. The first spike saw empty results only because it passed no query parameter (see round 2) | Not exposed. Document-type rights/privileges/user-groups/security paths and document-level equivalents return 404 |

## Round 2 (same day): open questions from the design

Read-only again, plus Hyland's public documentation: the
[Integration Server reference](https://hyland.github.io/integrationserver-docs/latest/operations.html),
[licensing](https://hyland.github.io/integrationserver-docs/latest/licensing.html),
[session management](https://hyland.github.io/integrationserver-docs/latest/sessionmanagement.html) and
Perceptive Content's
[privilege definitions](https://docs.hyland.com/r/Perceptive-Content/Manage-Content/Foundation-25.1/Manage-Content-User-Help/Privilege-definitions-overview).

### Perceptive Content

- **Readers can be computed from the source.** `GET /v2/userGroup/{id}/privilege?drawerId=…` returned
  `DOC_VIEW` for the Accounts Payable drawer as `GRANTED` for 13 groups (`AP Approver`, `AP Manager`, …)
  and `UNSET` for 37; `?documentTypeId=…` works the same way, and `/v2/user/{id}/privilege` gives
  user-level settings (1 of 60 users had one: `administrator`). These calls, plus `/v2/user` and
  `/v2/userGroup/{id}`, are free of transaction charges.
- **How privileges combine (Hyland docs).** User settings beat group settings; when two settings
  conflict, deny wins, including drawer against document type ("if a drawer privilege allows access and
  a document type privilege denies access … access is denied"); `UNSET` is a soft deny. Privileges apply
  only in the department where they were assigned.
- **Department managers bypass privileges.** The configured demo account belongs to one group with no
  privileges, yet opened documents in all 67 drawers that had any. It is a department manager of nearly
  every department (`/v1/department/{id}` lists `departmentManagers`). Its own group's drawer privileges
  answered 400 from its current department. So the one configured account cannot validate the reader
  rules; that needs ordinary (non-manager) accounts with known privileges.
- **Department visibility.** 117 of 167 groups answered 400 "not owned by the current department or
  has not been shared with the current department" for the demo account. What the service account can
  evaluate depends on its department.
- **Groups of one user.** `GET /v1/user/{id}/group` returns a user's groups in one call;
  `GET /v2/connection` returns the signed-in user's id and name. A full membership scan instead took
  191 calls and 32 s (23 departments, 167 groups).
- **Transaction licensing.** Every Integration Server call counts against a transaction licence except a
  short list of free calls (connection, user and group reads, privileges, server info). A crawl spends the
  customer's transaction budget roughly per document and per page file.
- **Sessions.** Reuse one session; Integration Server handles one call at a time per session; sessions
  expire after 60 idle minutes by default. Two concurrent sessions for one account worked.
- **Listings are capped at 500 with no paging.** `/v1/drawer/{id}` returned exactly 500 documents for
  Human Resources and Registrar and ignored every paging parameter tried. View results
  (`POST /v6/view/{id}/result`) also stop at 500 but set `hasMore`; the reference documents no offset.
  Narrowing the VSL works: `[drawer] = 'Registrar' AND [docId] < '321Z5'` returned 87 rows with
  `hasMore=false`, `… AND [docType] = 'Transcript'` 211. Views are tied to drawers; a view must cover
  the drawer and the account needs View > Access to run it.
- **Folders.** `GET /v5/folder/{id}` returns folder details, contents and `hasMoreContainedItems`.
- **Documents.** In a sample of 25: 18 had the id as their name, 14 had a modification time, page counts
  from 1 to 10, page files `tif`, `pdf`, `msg`, `doc`, `txt`, `jpg`.

### OnBase

- **Username.** The access token has a `username` claim equal to the login name, so search-side
  identities can use it unchanged.
- **Queries.** `DocumentTypeGroup` queries work and return the document name as a display column (no
  per-document call for names). `maxResults` is honoured as given (5000 returned all 1,376 System
  Documents) and nothing reports truncation, so a page must ask for one more than it keeps.
  `documentDateRangeCollection: [{start, end}]` narrows by document date. Three type groups answered 400
  ("Failed to add DocumentTypeGroup") for the demo account.

### Content Lake

- **Deny principals are not enforced.** `docs/security-model.md`: denies are stored as `cin_deny` "but
  take no part in the predicate". A connector whose source has deny-wins rules must resolve them itself
  and emit only who can read.

### Perceptive test fixture (dev server, created through the API)

Users, groups and privileges can be created through Integration Server (`POST /v1/user`,
`POST /v1/userGroup`, `PUT /v2/userGroup|user/{id}/privilege`, `POST /v1/document` + `/page`); drawers,
document types, views and **passwords** cannot. Created in the `Sandbox - GT` department, privileges set
only on the new groups and users (ids in `~/.cltest/perceptive-manifest.json`, removed by
`~/.cltest/teardown_perceptive.py`). Document types must belong to the groups' department (types from
other departments answer 400). Page files download as `application/octet-stream`.

| Document | Drawer (grants) | Type (grants) | Expected readers |
|---|---|---|---|
| restricted 1, restricted 2 (2 pages) | `GT-Human Resources` (A granted; `cltest-c` denied) | `GT - Grade Change` | `cltest-a` |
| open 1 | `GT-Financial Aid` (A, B granted) | `GT - Grade Change` | `cltest-a`, `cltest-b`, `cltest-c` |
| open denied-type | `GT-Financial Aid` (A, B granted) | `GT - W4` (A denied) | `cltest-b` |
| typeonly granted | `GT-UG Registrar` (none) | `GT - LOA` (B granted) | `cltest-b` if a type grant alone suffices |
| typeonly normal | `GT-UG Registrar` (none) | `GT - Grade Change` | nobody |

Groups: `CL Test A` = `cltest-a`, `cltest-c`; `CL Test B` = `cltest-b`. To compare these expectations
with what each user can really open, an administrator must set the three test users' passwords.

## Limitations to carry into the design, READMEs and upstream issue

1. **OnBase: no API reports who may read a document.** The OnBase connector uses an operator-configured
   mapping from document type groups or document types to OnBase user group names. Anything unmapped is
   skipped and reported, never ingested as readable by everyone. *Perceptive* readers are computed from
   drawer and document type privileges instead (round 2); the computed result is only as complete as
   the groups and users the service account can see (limitation 13).
2. **Security is copied at sync time.** Changes to the OnBase mapping, Perceptive privileges or group
   membership reach the index only when the affected content is re-synced; privilege changes do not
   change a document's modification time.
3. **Finer-grained source security is not reflected.** OnBase security keywords (which can hide
   individual documents from some users) are invisible to the API, so a mapped group may be granted
   documents some members cannot open. In Perceptive, folder type, view and category privileges and
   anything outside drawer and document type privileges are not evaluated.
4. **OnBase group names cannot be validated.** With no group API, mapped OnBase group names are taken as
   given; a typo silently grants nothing (safe, but invisible). Perceptive group ids can be checked
   against `/v1/userGroup`.
5. **Principals must exist in the caller's identity.** Retrieval matches the namespaced principals
   (`<authority>_#_<sourceId>`) against the signed-in caller. Callers must authenticate with identities
   (and group memberships) that correspond to the source's users and groups.
6. **No change feeds.** Both connectors walk their sources and rely on a real modification time to skip
   unchanged content; deletions are found by the host's reconciliation pass.
7. **Demo servers cannot prove permission behaviour.** As upstream does for SharePoint, each connector
   needs a mock of its API and an end-to-end test that a restricted document is not returned to the
   wrong user, plus validation by someone with administrative access to a real instance before it is
   called stable.
8. **Searching needs more than the connector jar.** In content-lake-app the plugin jars are loaded only
   by the ingesters. At query time the rag-service signs callers in and resolves their groups with
   per-source `CallerAuthenticator` and `SourceGroupResolver` implementations that are built into it
   (Alfresco, Nuxeo, CMIS, Entra today). Perceptive and OnBase callers therefore need small rag-service
   additions, off by default like the CMIS one; without them the mapped group principals match nobody.
9. **OnBase caller groups depend on the identity service client.** The IdentityService advertises a
   `group` claim (scopes `group`, `profile.group`), but the demo client is not allowed to request those
   scopes (`invalid_scope`), and its tokens carry no group claim. Group-based OnBase mappings work only
   when an administrator allows the `group` scope for the client the rag-service uses; until then only
   user-level (or everyone) mappings can match OnBase callers. Perceptive caller groups come from
   `/v1/user/{id}/group` in one call.
10. **OnBase keyword-only edits are not picked up.** OnBase documents carry no modified time; the
    connector uses the latest revision's creation time (falling back to `storedDate`). Changing a
    document's keywords does not create a revision, so keyword edits reach the index only when the
    document gets a new revision or is re-synced in full. The per-document audit log
    (`/documents/{id}/history`) records such edits but is too costly to read for every document.
11. **Perceptive crawls spend transaction licences.** Document, page and file calls are charged against
    the customer's Integration Server transaction licence; only connection, user, group and privilege
    reads are free. Operators must budget a full crawl and its re-syncs.
12. **Perceptive listings stop at 500.** Drawer listings and view results have no paging; the connector
    splits searches by narrowing VSL until each part reports no more results. It needs a document view
    covering each configured drawer that the service account may run.
13. **Perceptive privileges are department-scoped.** The service account can only read privileges of
    groups owned by or shared with its department. Where the readers of a drawer cannot be fully
    determined, its documents are skipped and reported rather than guessed.
14. **Perceptive managers are not granted through management rights.** Department managers (and
    owners) open content without holding privileges. The connector grants only what privileges grant,
    so a manager without privileges does not find that content through search.

## Option set aside for now

Probing as each group (one service account per group, recording which accounts can retrieve each
document) would reflect real source security, including OnBase security keywords. It needs credentials
for one account per group and multiplies API calls. Kept as a possible "accurate mode" later.
