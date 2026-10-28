# ACL Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenArch's permissions visible and demonstrable in Studio: demo personas with a switcher, side-by-side Ask, a readable permissions panel with live revoke and time-limited rules, and access on upload.

**Architecture:** An opt-in demo overlay mounts a users file into OpenArch (`openarch.users.file`) and Studio. Sessions gain an `origin` and an `active` identity; every existing route runs as `active`, so personas really sign in to OpenArch. New `acl.py` validates and maps rules; new `/access`, `/principals`, `/demo/*` routes read and write `sys_acl` through OpenArch; the web adds a switcher, a permissions panel, Ask Compare and an upload access step.

**Tech Stack:** FastAPI + httpx + pydantic-settings + PyYAML (api), React 18 + Vite + vitest/testing-library (web), Docker Compose overlay.

**Spec:** `docs/superpowers/specs/2026-10-28-acl-showcase-design.md`

All paths are relative to `pocs/openarch-studio/`. API tests: `cd api && .venv/bin/pytest -q`. Web tests: `cd web && npx vitest --run`. After `npm run build`, run `git checkout -- web/tsconfig.tsbuildinfo`.

## Global Constraints

- OpenArch is the only permission authority: Studio never decides who may read what; it shows `sys_acl`, `fulleffectiveacl`, `fulleffectivepermissions`, or what each identity retrieved.
- No changes outside `pocs/openarch-studio/`. No OpenArch Java changes.
- Passwords never leave the API process; no response or log contains a password.
- Demo mode only when `STUDIO_DEMO_MODE=true` (set only by `compose.demo.yaml`); without it, behaviour is unchanged.
- Permission whitelist (exact strings): `Read`, `ReadWrite`, `Write`, `ManageSecurity`, `Everything`.
- Every rule sent to OpenArch has `granted: true` (OpenArch rejects negative ACEs).
- Effective-permission calls use query parameter `usernames` with **user ids** (comma-joined).
- Personas (username / groups / `studioPersona`): `fiona` finance,members "Finance analyst"; `henry` hr,members "HR partner"; `sam` sales,members "Sales rep"; `erin` finance,hr,sales,members "Executive"; `cory` members "Contractor". All `password: "{noop}password"`.
- Demo folders: `Studio Demo` (root, Read `members`) → `Company` (Read `members`), `Finance` (Read `finance`), `HR` (Read `hr`), `Sales` (Read `sales`).
- No native `<select>`; pickers are searchable modals built on `components/Modal.tsx`.
- Copy (exact): banner "You're seeing what {Name} ({label}) can see"; "Back to Admin"; "Only users with Manage security can see the rules"; "You no longer have access to this folder"; "You don't have permission to change access here"; "You can't set access in this folder"; "Access changed meanwhile; reloaded".

## Review Focus

1. Demo setup or reset clicked while acting as a persona → runs with the **origin** (admin) credentials, not the persona's, and succeeds (Task 8).
2. A rule with `end` in the past, or `begin >= end` → 400 from Studio before any OpenArch call (Task 5).
3. An ancestor folder the caller can't read while building inherited rules → that ancestor is skipped, no 500 (Task 6).
4. `act-as` or chat `actAs` from a non-demo-admin origin, or for an unknown/unavailable persona → 403; acting as the origin itself is allowed (Tasks 3, 4).
5. A persona must not see another identity's jobs: `GET /api/jobs` omits them and `POST /api/jobs/{id}/retry` on someone else's job → 404 (Task 3).

---

### Task 1: Demo users file, overlay, and demo settings

**Files:**
- Create: `demo/openarch-users.yml`, `compose.demo.yaml`, `api/app/demo.py`, `api/tests/test_demo_users.py`
- Modify: `api/app/config.py`, `api/app/main.py`, `api/app/capabilities.py` (config response), `api/pyproject.toml` (add `pyyaml` if absent)

**Interfaces:**
- Produces: `Settings.demo_mode: bool = False`, `Settings.demo_users_file: str = ""`; in `demo.py`:
  `@dataclass(frozen=True) class Persona: username: str; user_id: str; label: str; groups: tuple[str, ...]; password: str | None` (None = unusable encoding);
  `@dataclass(frozen=True) class DemoUsers: personas: dict[str, Persona]; admins: frozenset[str]; group_ids: dict[str, str]`;
  `def load_demo_users(path: str) -> DemoUsers` (raises `DemoConfigError` when no persona has a usable password);
  `app.state.demo: DemoUsers | None`; `GET /api/config` gains `demoMode: bool`.

- [ ] **Step 1: Create `demo/openarch-users.yml`** — copy `../../server/openarch-app/src/main/resources/openarch-users.yml` verbatim, then append groups `finance` (`3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f01`), `hr` (`3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f02`), `sales` (`3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f03`) and the five personas from Global Constraints with ids `3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f11`…`…1f15` (fiona, henry, sam, erin, cory), each with `attributes: {studioPersona: <label>}`.

- [ ] **Step 2: Write failing tests** in `api/tests/test_demo_users.py` using `tmp_path` YAML fixtures:
  - `test_loads_personas_and_admins`: from the real `demo/openarch-users.yml` → `set(personas) == {"fiona","henry","sam","erin","cory"}`, `personas["erin"].groups == ("finance","hr","sales","members")`, `personas["sam"].label == "Sales rep"`, `personas["sam"].password == "password"`, `"admin" in admins`, `group_ids["sales"] == "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f03"`.
  - `test_bcrypt_persona_is_unavailable`: a persona with `{bcrypt}…` → `password is None`.
  - `test_no_usable_persona_raises`: only bcrypt personas → `DemoConfigError`.
  - `test_config_reports_demo_mode`: `create_app(Settings(..., demo_mode=True, demo_users_file=<real file>))` → `GET /api/config` has `demoMode: true`; default app → `false`.
  - `test_demo_mode_without_file_fails_startup`: `create_app(Settings(demo_mode=True, demo_users_file=""))` raises `DemoConfigError`.

- [ ] **Step 3: Run** `.venv/bin/pytest -q tests/test_demo_users.py` → FAIL (module missing).

- [ ] **Step 4: Implement** `load_demo_users` with `yaml.safe_load`; password usable only when it starts with `{noop}` (strip the prefix). `create_app` sets `app.state.demo = load_demo_users(...) if settings.demo_mode else None`. Config response adds `demoMode`.

- [ ] **Step 5: Create `compose.demo.yaml`** per spec §1 (mounts `./demo/openarch-users.yml` into `openarch-app` at `/etc/openarch/users.yml` and into `studio-api` at `/etc/studio/demo-users.yml`, both `:ro`; env `OPENARCH_USERS_FILE=file:/etc/openarch/users.yml`, `STUDIO_DEMO_MODE=true`, `STUDIO_DEMO_USERS_FILE=/etc/studio/demo-users.yml`).

- [ ] **Step 6: Run tests** → PASS. **Live check:** `OPENARCH_VERSION=1.0.60 docker compose -p studio-verify -f compose.yaml -f compose.demo.yaml up -d --build`, then `curl -s -o /dev/null -w '%{http_code}' -u sam:password http://localhost:8080/api/documents/00000000-0000-0000-0000-000000000000` → `200` or `403` (authenticated), **not** `401`. If `401`, replace the env var with `SPRING_APPLICATION_JSON={"openarch":{"users":{"file":"file:/etc/openarch/users.yml"}}}` and re-check.

- [ ] **Step 7: Commit** `feat(demo): demo users file, compose overlay, demo settings`.

### Task 2: Session origin/active and act-as

**Files:**
- Modify: `api/app/auth.py`, `api/app/models.py`, `api/app/routes.py`, `api/app/demo.py`
- Test: `api/tests/test_act_as.py`

**Interfaces:**
- Consumes: `DemoUsers`, `Persona` (Task 1).
- Produces: `@dataclass class Session: origin: Credentials; active: Credentials`; `SessionStore.get_session(session_id) -> Session | None`, `SessionStore.set_active(session_id, credentials: Credentials) -> None`; `SessionStore.get` keeps returning the **active** `Credentials` (so `current_credentials` is unchanged for callers);
  `def current_session(request, store) -> Session` (401 when missing);
  `def origin_credentials(session = Depends(current_session)) -> Credentials`;
  `def require_demo_admin(request, session = Depends(current_session)) -> DemoUsers` (403 unless demo mode and `session.origin.username in demo.admins`);
  `def persona_credentials(demo: DemoUsers, username: str, origin: Credentials) -> Credentials` (origin username → origin; available persona → its credentials; else raises 403);
  `SessionInfo` gains `actingAs: PersonaInfo | None`, `demoAdmin: bool`, where `PersonaInfo(username: str, label: str, groups: list[str])`;
  routes `POST /api/session/act-as {username}` → `SessionInfo`; `GET /api/demo/personas` → `[{username, label, groups, available}]` (404 when demo off; any signed-in user).

- [ ] **Step 1: Write failing tests** (respx mocks `GET {OA}/api/documents/{ROOT}` per user):
  - `test_act_as_persona_runs_requests_as_persona`: sign in admin (demo app), `POST /api/session/act-as {"username":"sam"}` → 200 `actingAs.username == "sam"`; a following `GET /api/documents` hits OpenArch with Basic auth for `sam`.
  - `test_back_to_origin`: act-as `admin` → `actingAs is None`, requests use admin again.
  - `test_act_as_rejected_when_demo_off`, `test_act_as_rejected_for_non_admin_origin` (sign in as `sam` directly), `test_act_as_unknown_persona` → 403.
  - `test_act_as_persona_signin_failure` (OpenArch 401 for that persona) → 502 with detail containing "Couldn't sign in as sam".
  - `test_session_reports_demo_admin`: `GET /api/session` → `demoAdmin: true` for admin in demo mode, `false` otherwise.
  - `test_personas_endpoint_hides_passwords`: response JSON contains no `"password"` key; 404 when demo off.
  - `test_sign_out_clears_persona`.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** Act-as authenticates with `OpenArchClient.authenticate()` as the target before `set_active`. Error detail for sign-in failure: `"Couldn't sign in as {username}; check the demo users file"`.

- [ ] **Step 4: Run full API suite** → PASS (existing tests unchanged).

- [ ] **Step 5: Commit** `feat(api): session origin/active and demo act-as`.

### Task 3: Jobs are owned by the identity that started them

**Files:**
- Modify: `api/app/enrichment.py` (`Job`, `JobStore`), `api/app/jobs.py`, `api/app/library.py` (upload creates job with owner)
- Test: `api/tests/test_jobs_owner.py`

**Interfaces:**
- Produces: `Job.owner: str`; `JobStore.create(doc_id, filename, owner: str) -> Job`; `JobStore.list_for(owner: str) -> list[Job]`. `to_dict()` does **not** include `owner`.

- [ ] **Step 1: Write failing tests:** `test_jobs_listed_only_for_active_identity` (admin uploads; after act-as `sam`, `GET /api/jobs` → `[]`; back to admin → 1 job); `test_retry_other_identity_job_is_404`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — every `store.create` call passes `credentials.username` (active identity); `GET /api/jobs` uses `list_for`; retry returns 404 when `job.owner != active username`.
- [ ] **Step 4: Run full API suite** → PASS.
- [ ] **Step 5: Commit** `fix(api): jobs visible only to the identity that started them`.

### Task 4: Chat `actAs`

**Files:**
- Modify: `api/app/chat.py`, `api/app/search.py`
- Test: `api/tests/test_chat_act_as.py`

**Interfaces:**
- Consumes: `current_session`, `persona_credentials` (Task 2).
- Produces: `ChatRequest.actAs: str | None = None`.

- [ ] **Step 1: Write failing tests:** `test_chat_act_as_uses_persona_credentials` (demo admin, `actAs: "erin"` → vector query sent with Basic auth for `erin`); `test_chat_act_as_forbidden_outside_demo` → 403 before streaming; `test_chat_act_as_origin_allowed`; `test_chat_scoped_folder_forbidden_message` (OpenArch 403 on retrieval with `scope` → `RUN_ERROR` message `"You no longer have access to this folder"`); `test_search_scoped_folder_forbidden_message` (`POST /api/search` with `scope`, OpenArch 403 → 403 detail with the same copy; without `scope` the detail stays "Not permitted").
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — resolve credentials before creating the stream: `actAs` set → `persona_credentials(request.app.state.demo, body.actAs, session.origin)` (403 when demo off); else `session.active`. Map `OpenArchForbidden` during retrieval with a scope to the exact copy above.
- [ ] **Step 4: Run full API suite** → PASS.
- [ ] **Step 5: Commit** `feat(api): chat can run as a demo persona`.

### Task 5: Rule model and validation (`acl.py`)

**Files:**
- Create: `api/app/acl.py`, `api/tests/test_acl_rules.py`

**Interfaces:**
- Produces:
  `PERMISSIONS = ("Read", "ReadWrite", "Write", "ManageSecurity", "Everything")`;
  `class Principal(BaseModel): kind: Literal["user", "group"]; id: str`;
  `class RuleIn(BaseModel): principal: Principal; permission: str; begin: datetime | None = None; end: datetime | None = None`;
  `def validate_rules(rules: list[RuleIn], now: datetime) -> None` (raises `HTTPException(400)`);
  `def to_sys_acl(rules: list[RuleIn]) -> list[dict]` → `[{"granted": True, "permission": p, "user"|"group": {"id": …}, "begin"?: iso, "end"?: iso}]` (ISO `YYYY-MM-DDTHH:MM:SS.000Z`, UTC; keys omitted when None);
  `def parse_access_field(raw: str | None) -> list[RuleIn] | None` (for form fields; `None`/empty → `None`; bad JSON → 400).

- [ ] **Step 1: Write failing tests:** permission not in whitelist (`"Bogus"`) → 400; `begin >= end` → 400; `end <= now` → 400; more than 50 rules → 400; `to_sys_acl` output for a group rule with `end` equals `[{"granted": True, "permission": "Read", "group": {"id": "g1"}, "end": "2026-10-28T16:06:07.000Z"}]`; every mapped rule has `granted is True`; `parse_access_field("not json")` → 400.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(api): ACL rule validation and mapping`.

### Task 6: Read access, principals, effective-permissions fix

**Files:**
- Create: `api/app/access.py` (router), `api/tests/test_access_read.py`
- Modify: `api/app/openarch.py` (`get_effective_acl`, add `get_effective_permissions`, `find_users`, `find_groups`), `api/app/main.py` (include router, **not** extension-gated)

**Interfaces:**
- Consumes: `current_session`, `app.state.demo` (Tasks 1–2).
- Produces:
  `OpenArchClient.get_effective_acl(doc_id, user_ids: list[str] | None = None)` and `get_effective_permissions(doc_id, user_ids: list[str]) -> dict` — both send `params={"usernames": ",".join(user_ids)}`;
  `OpenArchClient.find_users(name: str) -> list[dict]` (`GET /api/user?name=`), `find_groups(name: str) -> list[dict]` (`GET /api/group?name=`);
  `GET /api/documents/{id}/access` → spec §3 JSON (`canManage`, `rules[]` with `source.kind` `local|inherited`, `effective[]`);
  `GET /api/principals?q=` → `[{kind, id, name, label?}]`, max 20.

- [ ] **Step 1: Write failing tests:**
  - `test_access_splits_local_and_inherited`: doc `sys_acl` [user U1 ReadWrite], `sys_parentId` P1 → P1 `sys_acl` [group sales Read], P1 parent root (no acl) → rules: first `source.kind == "local"`, second `{"kind": "inherited", "id": "P1", "title": "Sales"}`.
  - `test_access_skips_unreadable_ancestor`: ancestor GET 403 → still 200, ancestor omitted.
  - `test_access_without_manage_security`: doc has no `sys_acl` → `canManage: false`, `rules: []`.
  - `test_effective_uses_usernames_param_with_ids`: demo mode → request to `fulleffectivepermissions` has `usernames` = the five persona ids; `effective[i]` has `username` and `label`; non-demo → active user's id looked up via `/api/user?name=`.
  - `test_principals_merges_users_and_groups`: `q=sa` → user `sam` (with `label: "Sales rep"`) and group `sales`; `q=""` → 400.
  - `test_existing_acl_route_sends_usernames` (old `/acl` route).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Ancestor walk follows `sys_parentId` until the root id, max 20 hops; status/begin/end copied from each ACE.
- [ ] **Step 4: Run full API suite** → PASS.
- [ ] **Step 5: Commit** `feat(api): readable access endpoint and principal search`.

### Task 7: Write access; access on upload and folder create

**Files:**
- Modify: `api/app/access.py`, `api/app/library.py` (upload + folders), `api/app/openarch.py` (if a 409 error class is needed: `OpenArchConflict`)
- Test: `api/tests/test_access_write.py`

**Interfaces:**
- Consumes: `validate_rules`, `to_sys_acl`, `parse_access_field` (Task 5).
- Produces: `PUT /api/documents/{id}/access {rules: RuleIn[]}` → the same shape as `GET …/access`; `POST /api/documents` accepts form field `access` (JSON string); `POST /api/folders` body gains `access: list[RuleIn] | None = None`.

- [ ] **Step 1: Write failing tests:**
  - `test_put_access_sends_local_rules_as_sys_acl` (exact PUT body `{"sys_acl": [...]}` with `granted: true`).
  - `test_put_access_forbidden_message` (OpenArch 403 → 403 detail "You don't have permission to change access here").
  - `test_put_access_conflict_message` (409 → 409 "Access changed meanwhile; reloaded").
  - `test_put_access_rejects_bogus_permission_before_openarch` (no PUT call made).
  - `test_upload_with_access_includes_sys_acl` (create payload has `sysfile_blob` **and** `sys_acl`); `test_upload_without_access_has_no_sys_acl`; `test_upload_access_forbidden_message` ("You can't set access in this folder").
  - `test_create_folder_with_access`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run full API suite** → PASS.
- [ ] **Step 5: Commit** `feat(api): edit access, and set access on upload and new folders`.

### Task 8: Demo setup/reset and sample documents

**Files:**
- Create: `demo/samples/Company/{employee-handbook,holiday-calendar-2027}.md`, `demo/samples/Finance/{bonus-budget-2027,q3-forecast}.md`, `demo/samples/HR/{bonus-policy-2027,salary-bands}.md`, `demo/samples/Sales/{commission-plan-2027,q4-pricing}.md`, `api/app/demo_setup.py` (router), `api/tests/test_demo_setup.py`
- Modify: `compose.demo.yaml` (mount `./demo/samples` at `/etc/studio/demo-samples:ro`, env `STUDIO_DEMO_SAMPLES_DIR`), `api/app/config.py` (`demo_samples_dir: str = ""`), `api/app/main.py`

**Interfaces:**
- Consumes: `require_demo_admin`, `origin_credentials` (Task 2), `to_sys_acl` (Task 5), upload path in `library.py` (factor its create-and-enrich body into `async def store_and_enrich(client, parent_id, filename, content, owner, background, access=None) -> dict` and reuse it).
- Produces: `POST /api/demo/setup` → `{"folders": {"Studio Demo": id, "Company": id, …}, "jobs": [jobId…]}`; `DELETE /api/demo` → 204.

- [ ] **Step 1: Write the sample documents** (synthetic, 120–300 words each). Facts that must appear: Finance `bonus-budget-2027.md` "2027 bonus pool: €1.2M"; HR `bonus-policy-2027.md` "bonus pool is 8% of base salary" and eligibility after 6 months; Sales `commission-plan-2027.md` commission rates and accelerators; Sales `q4-pricing.md` Enterprise list price and "discount floor: 18%"; HR `salary-bands.md` engineer bands; Company `employee-handbook.md` "bonus details are restricted to HR and Finance".
- [ ] **Step 2: Write failing tests:** `test_setup_creates_folders_with_group_acls` (exact `sys_acl` per folder, group ids from the users file); `test_setup_is_idempotent` (existing folders/files by title → no second create/upload); `test_setup_uses_origin_credentials_while_acting_as` (act-as `sam`, then setup → every OpenArch call uses admin Basic auth); `test_q4_pricing_gets_cory_read`; `test_setup_forbidden_for_non_admin`; `test_reset_deletes_studio_demo`.
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement.** Find-or-create by title among `browse_children`. Jobs are owned by the origin username.
- [ ] **Step 5: Run full API suite** → PASS.
- [ ] **Step 6: Commit** `feat(demo): one-click demo setup with sample documents`.

### Task 9: Web — session, switcher, banner, Demo menu

**Files:**
- Create: `web/src/components/PersonaPicker.tsx`, `web/src/session.tsx`, `web/tests/persona.test.tsx`
- Modify: `web/src/types.ts`, `web/src/api.ts`, `web/src/App.tsx`, `web/src/components/AppShell.tsx`, `web/src/styles.css`

**Interfaces:**
- Produces: types `PersonaInfo {username; label; groups: string[]}`, `Persona extends PersonaInfo {available: boolean}`, `SessionInfo {username; actingAs: PersonaInfo | null; demoAdmin: boolean}`, `AppConfig.demoMode: boolean`;
  api `actAs(username): Promise<SessionInfo>`, `listPersonas(): Promise<Persona[]>`, `setupDemo(): Promise<{folders: Record<string,string>; jobs: string[]}>`, `resetDemo(): Promise<void>`;
  `SessionProvider` + `useSession(): {session: SessionInfo; demoMode: boolean; refresh(): Promise<void>; generation: number}` — `generation` increments on every identity change; pages that load data include it in their effect dependencies;
  `<PersonaPicker open onClose onPick(username) personas current />` (searchable modal; disabled rows for unavailable personas).

- [ ] **Step 1: Write failing tests:** picker filters by typed text and shows labels and groups; unavailable persona is disabled; picking calls `actAs` and the banner shows "You're seeing what Sam (Sales rep) can see"; "Back to Admin" calls `actAs("admin")`; switcher and Demo menu hidden when `demoMode` is false or `demoAdmin` is false.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Switcher lives in the rail foot (`whoami`), as "Acting as: {name} ▾"; banner at the top of `.stage`. Demo menu (rail foot): **Set up demo** (then navigate to `/activity`) and **Reset demo** (confirm `Modal`). Library, Search, Ask, Graph, Activity add `generation` to their load effects. SearchPage shows the API's 403 `detail` when present instead of the generic permission message.
- [ ] **Step 4: Run web tests + build** → PASS.
- [ ] **Step 5: Commit** `feat(web): persona switcher, acting-as banner, demo menu`.

### Task 10: Web — permissions panel

**Files:**
- Create: `web/src/components/PermissionsPanel.tsx`, `web/src/components/PrincipalPicker.tsx`, `web/src/components/RuleEditor.tsx`, `web/tests/permissions.test.tsx`
- Modify: `web/src/pages/DocumentPage.tsx` (replace the JSON `<pre>` in the permissions tab), `web/src/api.ts`, `web/src/types.ts`, `web/src/styles.css`

**Interfaces:**
- Produces: types `AccessRule`, `AccessInfo`, `Principal`, `RuleInput` mirroring spec §3; api `getAccess(id)`, `putAccess(id, rules: RuleInput[])`, `searchPrincipals(q)`;
  `<PrincipalPicker open onClose onPick(p: Principal) />` (debounced `searchPrincipals`);
  `<RuleEditor value onChange />` (principal, permission chips from the whitelist, window quick picks `2 min`, `1 hour`, `end of day`, `custom`) — reused by Task 12;
  `<PermissionsPanel docId />`.

- [ ] **Step 1: Write failing tests:** grid renders effective permissions per person; local rule has **Remove**, inherited rule shows "Inherited from Sales" link to `/documents/<folderId>` and no Remove; rule with `end` 90 s ahead shows "expires in 1:30" (fake timers) and refetches after it passes; `canManage: false` shows "Only users with Manage security can see the rules"; adding a rule with "2 min" sends `PUT` with `end` ≈ now+120 s and the existing local rules; 403 shows "You don't have permission to change access here".
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Hint under inherited rules: "To restrict one document in a shared folder, move it to a restricted folder."
- [ ] **Step 4: Run web tests + build** → PASS.
- [ ] **Step 5: Commit** `feat(web): readable permissions panel with live edits and time windows`.

### Task 11: Web — Ask Compare

**Files:**
- Create: `web/src/components/CompareColumn.tsx`, `web/tests/compare.test.tsx`
- Modify: `web/src/pages/AskPage.tsx`, `web/src/api.ts` (`streamChat` gains optional `actAs` in its options), `web/src/styles.css`

**Interfaces:**
- Consumes: `PersonaPicker`, `useSession` (Task 9), `CitationList`, `RetrievalTrace`.
- Produces: `function diffCitations(left: Citation[], right: Citation[]): {leftOnly: string[]; rightOnly: string[]; both: string[]}` (by `docId`, in first-seen order) exported from `CompareColumn.tsx`.

- [ ] **Step 1: Write failing tests:** `diffCitations` cases (disjoint, overlap, duplicates); Compare toggle visible only when `demoMode && demoAdmin`; one question sends two `/api/chat` requests with `actAs` per column (defaults: active identity and `erin`); summary strip lists titles under "Only {left}", "Only {right}", "Both"; **Re-ask** in one column sends one request.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run web tests + build** → PASS.
- [ ] **Step 5: Commit** `feat(web): side-by-side Ask as two personas`.

### Task 12: Web — access on upload and new folder

**Files:**
- Modify: `web/src/pages/LibraryPage.tsx`, `web/src/api.ts` (`uploadDocument(file, parentId?, access?)`, `createFolder(title, parentId?, access?)`), `web/tests/library.test.tsx`

**Interfaces:**
- Consumes: `RuleEditor`, `RuleInput` (Task 10).

- [ ] **Step 1: Write failing tests:** default "Same as folder" sends no `access` field; "Also share with…" + one rule sends form field `access` with the JSON rules for every file of a multi-file upload; new-folder dialog sends `access` in the JSON body; 403 shows "You can't set access in this folder".
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run web tests + build** → PASS.
- [ ] **Step 5: Commit** `feat(web): choose who can access on upload and folder create`.

### Task 13: Docs and live verification

**Files:**
- Modify: `README.md`, `docs/TECHNICAL-DEEP-DIVE.md`, `GLOSSARY.md`, `api/app/capabilities.py`, `web/src/pages/HelpPage.tsx`, `.env.example`

- [ ] **Step 1: Docs.** README "Demo mode" section: overlay command, personas table, the three demo questions, the two demo scripts from spec §3, and "Demo mode is for local demos only; never point it at real users". Deep dive: session origin/active, `/access` + `/principals` + `/demo/*`, the verified OpenArch behaviour table. Glossary: persona, acting as, local rule, inherited rule. Capability map extensions: "Permission visualization" and "Persona compare" (owner `Studio`). `.env.example`: commented `STUDIO_DEMO_MODE`, `STUDIO_DEMO_USERS_FILE`, `STUDIO_DEMO_SAMPLES_DIR`.
- [ ] **Step 2: Full suites.** API and web tests pass; `npm run build` passes.
- [ ] **Step 3: Live check** on `OPENARCH_VERSION=1.0.60 docker compose -p studio-verify -f compose.yaml -f compose.demo.yaml up -d --build`: sign in admin → Set up demo → all jobs complete → acting as `sam`, Library shows only Company and Sales; Compare Sam vs Erin on "What's the 2027 bonus pool?" → different citations; live-revoke script → Sam's Sales citation disappears on Re-ask; time-limited script → Cory's citation present, then gone after 2 min with rule `ARCHIVED`; without the overlay, the app shows no switcher or Demo menu.
- [ ] **Step 4: Commit** `docs: demo mode, personas, access panel`.
