# ACL showcase (personas, compare, permissions, sharing) — design

Date: 2026-10-28 · Status: draft for review

## Goal

Make OpenArch's permission model visible and demonstrable in Studio, the way Tech Talk Live #183 demoed it:
the same question gives different, correctly cited answers depending on who asks; access can be granted,
revoked and time-limited live, and the effect shows up in search, Ask and the graph straight away.

Demo first, real management second: everything here also works as ordinary permission management for an
admin, but the first release is shaped around a live demo.

## Decisions (from brainstorming)

- Scope of this release: personas + switcher, one-click demo setup with sample documents, side-by-side Ask,
  readable permissions panel, live revoke, time-limited access, graph per persona, access on upload.
  Deferred: Library access badges.
- Identity switching: **demo mode with server-held persona credentials** (approach 1). Studio really signs in
  to OpenArch as each persona; it never evaluates permissions itself. Rejected: browser-driven re-login
  (passwords in the browser), and "view as" by filtering admin results (Studio deciding access, wrong top-k).
- Without the demo overlay, Studio behaves exactly as today.

## Invariants

- **OpenArch is the only permission authority.** Studio displays what OpenArch reports and sends ACL
  changes to OpenArch; it never computes who may read what. Anything Studio shows about access comes from
  `sys_acl`, `fulleffectiveacl` or `fulleffectivepermissions`, or from what each identity actually retrieved.
- No OpenArch Java module changes. The demo users file is mounted through OpenArch's existing
  `openarch.users.file` property.
- Passwords never reach the browser. Persona credentials live in API memory only, like today's session.
- Demo mode is opt-in (`STUDIO_DEMO_MODE=true`, set only by `compose.demo.yaml`) and documented as
  local-demo-only.

## Verified OpenArch 1.0.60 behaviour (test stack, 2026-10-28)

| Fact | Consequence |
|---|---|
| `sys_acl` is accepted on `POST /api/documents/{parentId}` | Folders and uploads can be created with access in one call. |
| Folder ACEs are inherited by children | Department folders carry the rules; documents inherit. |
| Non-admin users see nothing unless granted | Personas need demo content shared with them. |
| `PUT /api/documents/{id}` with `sys_acl` replaces the document's local ACL | Edits are read-modify-write of local rules. |
| Revoke is immediate for the document and its embedding chunks (no re-index wait) | Live revoke works. |
| An ACE with `end` stops granting within ~15 s of expiry; its status becomes `ARCHIVED` | Time-limited demo with a 2-minute window works. |
| Negative ACEs are rejected (`Negative ACL not allowed`); REST has no block-inheritance | No "deny here". Restrict by editing the folder rule or moving the document. |
| Any `permission` string is accepted (even `Bogus`) | Studio whitelists permission names. |
| `fulleffectivepermissions` / `fulleffectiveacl` take **user ids** in `usernames` | The existing client sends `users` and gets nothing back — fixed here. |
| `fulleffectiveacl` returns local and inherited ACEs per user; `fulleffectivepermissions` returns the expanded set (ReadWrite → Read, Write, Delete, …) | Panel data comes straight from these. |
| `sys_acl` is only returned to callers with `ManageSecurity` | Non-managers see their own effective permissions only. |
| A query scoped by `sys_ancestorIds` to an unreadable folder returns 403, not an empty list | Studio maps it to a clear "no longer have access to this folder" message. |

Permission names offered and accepted by Studio: `Read`, `ReadWrite`, `Write`, `ManageSecurity`,
`Everything` (`SecurityConstants`).

## 1. Personas and demo setup

### Demo users file

`demo/openarch-users.yml` is a copy of OpenArch's default users file (same groups, users and UUIDs, so
nothing that worked before breaks) plus:

- groups `finance`, `hr`, `sales` (new fixed UUIDs);
- personas, each with `password: "{noop}password"` and `attributes.studioPersona` (the label Studio shows):

| Username | Groups | `studioPersona` |
|---|---|---|
| `fiona` | finance, members | Finance analyst |
| `henry` | hr, members | HR partner |
| `sam` | sales, members | Sales rep |
| `erin` | finance, hr, sales, members | Executive |
| `cory` | members | Contractor |

### Compose overlay

`compose.demo.yaml`, used as `docker compose -f compose.yaml -f compose.demo.yaml up -d`:

- `openarch-app`: mounts `demo/openarch-users.yml` read-only and sets
  `OPENARCH_USERS_FILE=file:/etc/openarch/users.yml` (Spring relaxed binding for `openarch.users.file`;
  first implementation step verifies a persona can sign in, else falls back to
  `SPRING_APPLICATION_JSON`).
- `studio-api`: mounts the same file read-only at `/etc/studio/demo-users.yml` and sets
  `STUDIO_DEMO_MODE=true`, `STUDIO_DEMO_USERS_FILE=/etc/studio/demo-users.yml`.

### Personas in the API (`api/app/demo.py`)

- On startup in demo mode, parse the users file: personas are users with `attributes.studioPersona`;
  demo admins are users in any `administratorsGroups` group. Only `{noop}` passwords are usable; a persona
  with any other encoding is listed as unavailable. Demo mode with zero usable personas fails startup
  with a clear error.
- Persona user ids come from the file (they match OpenArch's ids by construction).
- `GET /api/demo/personas` → `[{username, label, groups, available}]` (no passwords). 404 when demo mode
  is off.

### One-click demo setup

- `POST /api/demo/setup` (demo admin only): idempotent, find-or-create by title.
  - Folder `Studio Demo` at root, readable by `members`.
  - Children `Company` (Read: `members`), `Finance` (Read: `finance`), `HR` (Read: `hr`),
    `Sales` (Read: `sales`), each created with `sys_acl`.
  - Uploads every file in `demo/samples/<Folder>/` not already present by name, using the normal upload
    path (enrichment starts as usual). Returns the folder ids and the list of started jobs.
  - `Sales/q4-pricing.md` additionally gets a document-level `Read` for `cory` with no end date (the
    live time-limit is added by hand during the demo).
- `DELETE /api/demo` (demo admin only): deletes `Studio Demo` (children go with it).
- UI: a **Demo** menu in the header (demo mode + demo admin only) with **Set up demo** (shows progress
  through the Activity page) and **Reset demo** (confirm dialog).

### Sample documents (`demo/samples/`)

Short, synthetic Markdown written for this project (no third-party content), designed so one question
gets different answers per persona:

| Folder | Documents | What they hold |
|---|---|---|
| Company | `employee-handbook.md`, `holiday-calendar-2027.md` | Bonuses exist; "details are restricted to HR and Finance". |
| Finance | `bonus-budget-2027.md`, `q3-forecast.md` | 2027 bonus pool €1.2M; revenue forecast. |
| HR | `bonus-policy-2027.md`, `salary-bands.md` | Bonus pool 8% of base, eligibility rules. |
| Sales | `commission-plan-2027.md`, `q4-pricing.md` | Commission rates, accelerators; list prices and discount floors. |

Demo questions (documented in the README): "What's the 2027 bonus pool?", "What discount can I give on
the Enterprise plan?", "What are the salary bands for engineers?"

## 2. Switcher, side-by-side Ask, graph per persona

### Session model (`auth.py`)

A session holds `origin` (who signed in) and `active` (who requests run as). `current_credentials` returns
`active`, so every existing route — Library, Search, Ask, Graph, Activity — runs as the active identity with
no change. Outside demo mode `active` is always `origin`.

- `POST /api/session/act-as` `{username}` (demo mode; origin must be a demo admin; username must be an
  available persona or the origin itself): signs in to OpenArch as that persona (`GET` root, as login does
  today) and sets `active`. 403 otherwise; 502 if the persona's sign-in fails.
- `GET /api/session` gains `actingAs: {username, label} | null` and `demoAdmin: bool`.
- Signing out clears both.

### Activity jobs

`GET /api/jobs` today lists every user's jobs, which would leak titles of documents a persona can't read.
Jobs record the username that started them; `GET /api/jobs` returns only the active identity's jobs, and
retry is limited the same way.

### Header switcher (web)

- **Acting as: Admin ▾** opens a searchable modal (no native select) listing personas with label, groups and
  initials; unavailable personas are shown disabled with the reason.
- While acting as a persona, a persistent coloured banner: "You're seeing what Sam (Sales rep) can see ·
  Back to Admin". Switching refetches the current page's data.

### Side-by-side Ask

- `ChatRequest` gains optional `actAs: string`. Allowed only in demo mode for a demo-admin origin and an
  available persona (or the origin); the request then runs with that persona's credentials. Otherwise 403.
- Ask page **Compare** toggle: two columns, each with its own persona picker (defaults: the active identity
  and `erin`). One question box sends two `/api/chat` requests in parallel, one per column; each column
  renders its own streamed answer, citations and retrieval trace.
- Summary strip under the columns: documents cited only on the left, only on the right, and by both —
  computed from the two citation lists, nothing else.
- Each column has **Re-ask** (same question, that column only).

### Graph per persona

No backend change: `/api/graph` already builds from the documents the caller can read. The switcher and
banner make the difference visible.

## 3. Readable permissions panel, live revoke, time-limited access

### Read (`GET /api/documents/{id}/access`)

Runs as the active identity. Response:

```json
{
  "canManage": true,
  "rules": [
    {"principal": {"kind": "group", "id": "…", "name": "sales"}, "permission": "Read", "granted": true,
     "begin": null, "end": "2026-10-28T16:06:07Z", "status": "EFFECTIVE",
     "source": {"kind": "inherited", "id": "<folder id>", "title": "Sales"}}
  ],
  "effective": [{"userId": "…", "username": "sam", "label": "Sales rep", "permissions": ["Read"]}]
}
```

- `canManage`: the document came back with `sys_acl` (OpenArch only includes it for `ManageSecurity`).
- `rules`: local rules from the document's `sys_acl` (`source.kind = "local"`), then inherited rules from
  each ancestor's `sys_acl`, nearest first (`source.kind = "inherited"`, with that folder's id and title).
  Only when `canManage`.
- `effective`: `fulleffectivepermissions?usernames=<ids>` for the personas (demo mode) or the active user
  (otherwise). Fixes the existing `users` → `usernames` bug; `get_effective_acl` is updated the same way.

### Write (`PUT /api/documents/{id}/access`)

Body: `{"rules": [{principal: {kind, id}, permission, begin?, end?}]}` — the document's **local** rules
only. The API validates (permission in the whitelist; principal kind `user`/`group`; `begin < end` when
both set; at most 50 rules), re-reads the document, and sends `PUT /api/documents/{id}` with `sys_acl` as
the active identity. OpenArch's 403 maps to "You don't have permission to change access here". All rules
are sent as `granted: true` (OpenArch rejects denies).

### Principal search (`GET /api/principals?q=`)

`/api/user?name=` and `/api/group?name=` as the active identity, merged: `[{kind, id, name, label?}]`.
Personas carry their `studioPersona` label. Minimum query length 1, at most 20 results.

### Panel UI (document **Permissions** tab; folders get the same panel)

- **Who can access**: grid of people × Read / Write / Manage security, from `effective`.
- **Access rules**: one row per rule with principal chip, permission, Granted, time window with a live
  countdown ("expires in 1:42"), OpenArch status, and source ("Set here" or "Inherited from Sales ›").
  Inherited rows link to the folder's panel; they have no remove button.
- **Add rule** (when `canManage`): principal from the searchable modal, permission, optional window with
  quick picks **2 min · 1 hour · end of day · custom**.
- **Remove** on local rules.
- Without `canManage`: your own effective permissions and "Only users with Manage security can see the
  rules".
- After an expiry passes, the panel refetches so the status visibly becomes `ARCHIVED`.
- Hint under inherited rules: to restrict one document inside a shared folder, move it (existing Move).

### Demo scripts (README)

- *Live revoke*: Compare Sam vs Erin on "What discount can I give on the Enterprise plan?" → open the
  Sales folder's permissions → remove `sales` → Re-ask in Sam's column → the citation is gone.
- *Time-limited*: on `q4-pricing.md` add `cory` Read for 2 min → Compare Cory vs Erin, Cory cites it →
  after expiry the rule shows `ARCHIVED` → Re-ask, Cory can't.

## 4. Access on upload and new folders

- Upload dialog **Who can access** step: default **Same as folder** (no `sys_acl`, as today); or **Also
  share with…**: principals from the searchable modal, a permission, optional end. Applied to every file in
  a multi-file upload.
- `POST /api/documents` accepts an optional `access` form field (JSON, same rule shape and validation as
  `PUT …/access`) and sends it as `sys_acl` in the create call that already carries `sysfile_blob`.
- `POST /api/folders` accepts the same optional `access`.
- OpenArch's 403 surfaces as "You can't set access in this folder".

## Errors and edge cases

- Persona sign-in fails at act-as → 502 with "Couldn't sign in as <persona>; check the demo users file".
- Act-as or `actAs` outside demo mode or from a non-admin origin → 403.
- Scoped search or Ask on a folder the identity can't read → 403 → "You no longer have access to this
  folder" (Search page message; Ask `RUN_ERROR` text).
- `PUT …/access` conflict (document changed) → OpenArch's 409 → "Access changed meanwhile; reloaded".
- A rule whose principal no longer exists is shown with its raw id and can still be removed.

## Testing

- API (pytest + respx): users-file parsing (personas, admins, `{noop}` only, startup failure with zero
  personas); act-as rules (demo off, non-admin origin, unknown persona, failed sign-in); `actAs` on chat;
  jobs filtered by owner; `/access` read (local vs inherited, `canManage`, `usernames` param with ids) and
  write (whitelist, window validation, 403/409 mapping, `granted: true` only); `/principals`; upload and
  folder `access`; demo setup idempotency and reset.
- Web (vitest): switcher modal and banner; Compare summary strip from two citation lists; permissions
  panel rendering of local/inherited/archived rules and countdown; upload access step.
- Live check on the 1.0.60 stack with the overlay: personas sign in; demo setup; the three demo questions
  answered differently per persona; both demo scripts end to end.
- `eval` is unaffected (it signs in as a single user and never uses demo mode).

## Docs

README (demo mode section with the overlay command, personas table, demo scripts, local-only warning),
TECHNICAL-DEEP-DIVE (session origin/active, access endpoints, verified OpenArch behaviour), GLOSSARY
(persona, acting as, local vs inherited rule), Capability map (ACL entries stay native; "Permission
visualization" and "Persona compare" as Studio extensions), `.env.example`.

## Out of scope

- Library access badges (next release; reuses `/access`).
- Deny rules and blocking inheritance (not supported by OpenArch's REST API).
- Real identity providers, user/group administration, and persistent sessions.
