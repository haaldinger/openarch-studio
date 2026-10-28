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
| Metadata and change time | `/v7/document/{id}`: document type, drawer, index fields `field1`–`field5`, creation and modification user and time | Keyword types (`/keyword-types`, with a per-type `isSecurityMasked` flag); document keywords per document |
| Users and groups | Users (`/v2/user`); departments (`/v1/department`); user groups per department (`/v1/userGroup?departmentId=`) with members (`/v1/userGroup/{id}`) | None found: `/users`, `/user-groups`, `/groups` return 404 |
| Who can read a document | Not exposed. `/v2/drawer/{id}` reports only the signed-in account's own rights (`canSearchContent`, …). Document privilege/security/ACL paths return 404. `/v1/userGroup/{id}/privilege` exists but returned no privilege sets for any of ~60 groups checked | Not exposed. Document-type rights/privileges/user-groups/security paths and document-level equivalents return 404 |

## Limitations to carry into the design, READMEs and upstream issue

1. **Neither API reports who may read a document.** The connectors therefore cannot reproduce source
   security exactly. They use an operator-configured mapping from containers to principals:
   Perceptive drawers → Perceptive user groups; OnBase document type groups or document types → OnBase
   user group names. Anything unmapped is skipped and reported, never ingested as readable by everyone.
2. **The mapping is a copy, not a sync.** When source security changes (groups, drawer privileges,
   document type rights), the index follows only after the mapping is updated and the content
   re-synced.
3. **Finer-grained source security is not reflected.** Perceptive document- or folder-level
   restrictions inside a drawer and OnBase security keywords (which can hide individual documents from
   some users) are invisible to the API used here. A mapped group may therefore be granted documents
   that some of its members cannot open in the source. Deployments that rely on these controls must
   not use the mapping as-is.
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

## Option set aside for now

Probing as each group (one service account per group, recording which accounts can retrieve each
document) would reflect real source security, including OnBase security keywords. It needs credentials
for one account per group and multiplies API calls. Kept as a possible "accurate mode" later.
