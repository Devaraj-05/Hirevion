# SP-02b Organisations and Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organisation, user and role management on top of SP-02a's sign-in, as specified in `docs/superpowers/specs/2026-10-01-sp-02-identity-access-design.md` ("SP-02b"). It covers:
- the organisation profile, departments and teams;
- users, with email invitations;
- custom roles and the permission matrix;
- resource scoping;
- step-up re-authentication;
- auditing of permission changes;
- super-admin create, suspend and reactivate for organisations;
- the admin and platform pages;
- the authorisation-matrix test (every endpoint × every role).

**Architecture:**

- **`hirevion_core.access`** holds the domain as plain async functions over an `AsyncSession` the route opens with `db.tenant(...)`:
  - `organization` (profile), `structure` (departments and teams), `users`, `roles`, `platform` (organisations);
  - `scope`: the resource scope later sub-projects filter by;
  - `errors`: typed refusals the API turns into RFC 9457 problems.
- **Permissions:**
  - System roles keep their permissions in code (`SYSTEM_ROLES`).
  - Custom roles store theirs in `role_permissions`.
  - A request's permissions are loaded from the database each time, so a role change applies at once.
- **`hirevion_api.authz`:**
  - **`Principal`:** the session plus its permissions.
  - **`requires(permission, step_up=...)`:** the only way a route is guarded.
  - **`UNGUARDED`:** the reviewed list of routes that need no permission.
  - **The matrix test** walks every route and checks every role against it, so a later sub-project can't add an unguarded route by accident.
- **Cross-tenant platform work:**
  - **Reading every organisation** uses a `SECURITY DEFINER` function owned by `hirevion_auth`, as the sign-in lookups do.
  - **Creating an organisation** runs in the new organisation's own tenant transaction; the app role gets `INSERT` on `organizations`, still bounded by the tenant policy.
  - **Both audit chains** (the organisation's and the platform's) are written in that same transaction by switching `app.org_id`.
- **The web app:**
  - **Pages:** the six SP-02 pages, built from `@hirevion/ui`'s `DataTable`, dialogs and forms, calling the API with TanStack Query.
  - **Step-up:** a step-up dialog retries any call refused with `step-up-required`.
  - **Development sessions** see an empty state that asks them to sign in for real, as the account page does.

**Tech Stack:**
- **Existing:** FastAPI, SQLAlchemy 2 async, Alembic, asyncpg, Jinja2 mail; Next 16, next-intl, TanStack Query and Table, `@hirevion/ui`; Playwright 1.63.0.
- **No new dependencies.**

## Global Constraints

- **Master plan §13 applies to every task:**
  - UUIDv7 keys and UTC `timestamptz`;
  - `organization_id` and forced row-level security on every tenant table, with composite `(organization_id, id)` foreign keys;
  - RFC 9457 problems, cursor pagination and `Idempotency-Key` on creates;
  - every string externalised (en-IN and en-US);
  - WCAG 2.2 AA;
  - TDD;
  - at least 85% line coverage on domain modules;
  - every authorisation and tenancy path tested.
- **Authorisation is checked on the server, in every route** (PRD §81). The web app's hiding of pages and buttons is convenience only.
- **Nobody can grant a permission they don't hold:**
  - not by creating or editing a role;
  - not by assigning one;
  - not by inviting with one.

  Custom roles never carry `platform.*` permissions.
- **Every organisation keeps at least one active user with its admin system role:** `org_admin`, or `super_admin` in the Platform organisation. Super admins hold every permission, so the admin pages also work on the Platform organisation; inviting another super admin is just inviting a user with `super_admin` there.
- **Step-up:** role changes, invitations, disabling or enabling a user, custom-role changes and every platform organisation change need a password confirmed within the last `HV_STEP_UP_MINUTES` (10). Wrong step-up passwords count towards the same lockout as sign-in.
- **Audit (PRD §97 "Permissions changed"):** every change made here is appended to the affected organisation's chain. Platform actions are also appended to the platform chain.
- **Secrets never appear in logs, problems, audit details or test output:** passwords, tokens, invitation links.
- **The web app keeps its development sessions,** and the route × role Playwright suite keeps running without an API.
- **Git:** commit as Devaraj-05 only, with no AI attribution (CLAUDE.md).

## Decisions this plan makes (recorded in ADR-0014 in Task 13)

1. **Invitations are users with status `invited`** plus SP-02a's 72-hour `set_password` token, with no separate `user_invitations` table:
   - Accepting is the existing `/set-password/[token]` page, which activates the user and verifies the email.
   - A resend revokes earlier unused tokens.
   - A cancel deletes the invited user.
2. **Resource scope** (the "organisation-wide, optional team limit" decision):
   - Each user has `access_scope`: `organization` (default) or `teams`.
   - `teams` limits them to work owned by one of their teams, or by them.
   - The rule ships here as `ResourceScope` and `scope_clause()`. SP-04 (jobs, candidates) and SP-07 (interviews) apply it.
   - Assignment, which narrows hiring managers and interviewers further, arrives with those resources.
3. **The session contract** gains `custom_roles` (names); `roles` stays the system role keys. Every session also holds `account.manage` (`BASELINE_PERMISSIONS`).
4. **Role names** are unique per organisation, case-insensitively, including the system roles' names (`roles.name` becomes citext).
5. **Departments and teams are archived, never deleted,** so later jobs can keep pointing at them.
6. **An admin who invites an address already in use** learns only that it is in use (409 `email-taken`), not which organisation has it.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/migrations/versions/0008_organizations_access.py` | Profile columns, `departments`, `teams`, `team_members`, `role_permissions`, `roles.description` and citext name, `users.access_scope`, `web_sessions.stepped_up_at`, `auth_session()` v2, `platform_organizations()`, `INSERT` on `organizations` |
| `backend/core/src/hirevion_core/models/{organization,role,user,web_session}.py` | New columns |
| `backend/core/src/hirevion_core/models/{department,team}.py` | `Department`, `Team`, `TeamMember` (`RolePermission` goes in `role.py`) |
| `backend/core/src/hirevion_core/db/session.py` | `switch_tenant(session, organization_id)` |
| `backend/core/src/hirevion_core/identity/permissions.py` | `BASELINE_PERMISSIONS`, `ASSIGNABLE_PERMISSIONS`, `permissions_for(role_keys, granted)` |
| `backend/core/src/hirevion_core/identity/grants.py` | `Grants`, `load_grants(session, user_id)` |
| `backend/core/src/hirevion_core/identity/{sessions,service,settings,tokens}.py` | `stepped_up_at`, `step_up`, `HV_STEP_UP_MINUTES`, `revoke_tokens` |
| `backend/core/src/hirevion_core/access/{__init__,errors,actor,audit,scope}.py` | Access core |
| `backend/core/src/hirevion_core/access/{organization,structure,users,roles,platform}.py` | Admin domain |
| `backend/core/src/hirevion_core/mail/templates/{en-IN,en-US}/invitation.*.j2` | Invitation email |
| `backend/api/src/hirevion_api/authz.py` | `Principal`, `Requires`, `requires`, `UNGUARDED`, `route_requirement` |
| `backend/api/src/hirevion_api/access/{__init__,deps,errors,schemas,organization,structure,users,roles,platform}.py` | Routers |
| `backend/api/tests/test_authorization_matrix.py` | Every route × every role |
| `tools/devcli/src/hirevion_devcli/identity.py` | Seed a department and a team |
| `recruitment-platform/src/admin/**` | API calls, step-up dialog, dev notice, the six page bodies |
| `recruitment-platform/src/auth/{session,permissions}.ts`, `src/account/account-body.tsx` | `customRoles` |
| `recruitment-platform/messages/{en-IN,en-US}.json` | `admin`, `platform`, `permissionLabels`, `stepUp` |
| `recruitment-platform/e2e/auth/admin.spec.ts` | Real-API admin flows |
| `docs/architecture/adr/0014-organizations-and-access.md`, `docs/runbooks/local-dev.md`, `MASTER_IMPLEMENTATION_PLAN.md` §7 | Docs |

---

### Task 1: Schema for organisations, structure, custom roles, scope and step-up

**Files:**
- Create: `backend/migrations/versions/0008_organizations_access.py`
- Create: `backend/core/src/hirevion_core/models/department.py`, `models/team.py`
- Modify: `models/{organization,role,user,web_session,__init__}.py`
- Modify: `db/session.py` (`switch_tenant`)
- Tests: `backend/core/tests/db/test_access_schema.py` (new); `test_identity_schema.py` (function list); `test_models_match_migrations.py` and the isolation harness (unchanged, must stay green)

**Interfaces (produces):**
- **`Organization`** gains:
  - `website: str | None`;
  - `country: str` (ISO 3166-1 alpha-2, default `IN`, check `^[A-Z]{2}$`);
  - `timezone: str` (IANA, default `Asia/Kolkata`);
  - `default_locale: str` (`en-IN` | `en-US`, default `en-IN`).
- **`Department`** (`departments`): `id`, `organization_id`, `name` (citext), `description`, `archived_at`, timestamps. Unique (`organization_id`, `name`) and (`organization_id`, `id`).
- **`Team`** (`teams`):
  - columns: `id`, `organization_id`, `name` (citext), `description`, `department_id` (nullable), `archived_at`, timestamps;
  - a composite foreign key (`organization_id`, `department_id`) → `departments`;
  - unique (`organization_id`, `name`) and (`organization_id`, `id`).
- **`TeamMember`** (`team_members`):
  - columns: `organization_id`, `team_id`, `user_id`, `created_at`;
  - primary key (`team_id`, `user_id`);
  - composite foreign keys to `teams` and `users`, `ON DELETE CASCADE`;
  - index on `user_id`.
- **`RolePermission`** (`role_permissions`, in `models/role.py`):
  - columns: `organization_id`, `role_id`, `permission` (text, check `^[a-z_]+(\.[a-z_]+)+$`);
  - primary key (`role_id`, `permission`);
  - a composite foreign key to `roles`, cascade.
- **`Role`** gains `description: str | None`. `name` becomes citext, with unique (`organization_id`, `name`).
- **`User`** gains `access_scope: str` (`organization` | `teams`, default `organization`). `ACCESS_SCOPES = ("organization", "teams")` lives in `models/user.py`.
- **`WebSession`** gains `stepped_up_at: datetime | None`.
- **`auth_session(p_token_hash bytea)`** now also returns `stepped_up_at`, after `revoked_at`.
- **`platform_organizations()`:**
  - returns table (`id`, `name`, `slug`, `status`, `created_at`, `user_count` bigint);
  - `STABLE SECURITY DEFINER SET search_path = public, pg_temp`, owned by `hirevion_auth`;
  - `EXECUTE` granted to `hirevion_app` only.
- **`switch_tenant(session: AsyncSession, organization_id: UUID) -> None`** runs `SELECT set_config('app.org_id', :org, true)` inside the caller's transaction. It is used only for platform actions that write two chains.

- [ ] **Step 1: Write the failing tests** (`pytest -m db`, `test_access_schema.py`):
  - **Tenancy:** as `hirevion_app` in organisation A, `departments`, `teams`, `team_members` and `role_permissions` show only A's rows, and inserting a row for B fails. Use the existing `make_organization` and `make_user` fixtures.
  - **Composite keys:**
    - a team can't point at another organisation's department;
    - `team_members` can't join A's team to B's user (foreign key violation).
  - **Names:**
    - two departments called `Engineering` and `engineering` in one organisation conflict, while the same name in two organisations is fine;
    - a custom role named `recruiter` conflicts with the system role `Recruiter`.
  - **Organisation inserts:** `hirevion_app` can insert an organisation only inside `db.tenant(<that new id>)`. Inserting under another tenant id fails the policy check.
  - **`platform_organizations()`:**
    - lists every organisation, including the Platform one, with its user count, when called with no tenant;
    - `PUBLIC` can't execute it.
  - **`auth_session()`** returns `stepped_up_at`.
  - **`switch_tenant`:** inside one `db.tenant(A)` transaction, `switch_tenant(B)` makes B's rows visible and A's invisible.
  - **Update `test_identity_schema.py`:** the list of functions `hirevion_app` may execute is now `auth_user_by_email`, `auth_session`, `auth_token` and `platform_organizations`.
- [ ] **Step 2: Run them:** `uv run pytest backend/core/tests/db/test_access_schema.py -m db`. They fail, because the tables don't exist.
- [ ] **Step 3: Write the migration.**
  - **Pattern:** follow `0006_identity.py` exactly: `_timestamps()`, `_organization_fk`, `tenant_policy_sql`, `grant_sql`, and `op.f(...)` constraint names.
  - **Grants:**
    - `departments` and `teams`: `SELECT, INSERT, UPDATE`;
    - `team_members` and `role_permissions`: `SELECT, INSERT, DELETE`;
    - `DELETE` added on `roles` and `users` (a cancelled invitation deletes the user);
    - `INSERT` added on `organizations`.
  - **Swapping `auth_session`'s return type:**
    ```sql
    DROP FUNCTION auth_session(bytea);
    CREATE FUNCTION auth_session(p_token_hash bytea)
    RETURNS TABLE (
        session_id uuid, user_id uuid, organization_id uuid, csrf_hash bytea,
        last_seen_at timestamptz, expires_at timestamptz, revoked_at timestamptz,
        stepped_up_at timestamptz, user_status text, organization_status text
    ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        SELECT s.id, s.user_id, s.organization_id, s.csrf_hash, s.last_seen_at, s.expires_at,
               s.revoked_at, s.stepped_up_at, u.status, o.status
        FROM web_sessions s
        JOIN users u ON u.organization_id = s.organization_id AND u.id = s.user_id
        JOIN organizations o ON o.id = s.organization_id
        WHERE s.token_hash = p_token_hash
    $$;
    ```
    Then repeat 0006's owner change, `REVOKE ALL … FROM PUBLIC` and `GRANT EXECUTE … TO hirevion_app`.
  - **`platform_organizations()`:**
    ```sql
    CREATE FUNCTION platform_organizations()
    RETURNS TABLE (id uuid, name text, slug citext, status text, created_at timestamptz,
                   user_count bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        SELECT o.id, o.name, o.slug, o.status, o.created_at,
               (SELECT count(*) FROM users u WHERE u.organization_id = o.id)
        FROM organizations o
    $$;
    ```
    Give it the same owner, revoke and grant statements.
  - **Downgrade:** reverse everything, and restore 0006's `auth_session`.
- [ ] **Step 4: Write the models and `switch_tenant`,** and export the new models from `models/__init__.py`. Update `resolve_session` in `identity/sessions.py` to read the new column; it carries through in Task 3.
- [ ] **Step 5: Run** `uv run hv migrate`, then `uv run pytest backend -m db`. Everything should be green, including `test_models_match_migrations` and the isolation harness.
- [ ] **Step 6: Run the checks:** `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy tools/devcli/src backend/core/src backend/api/src`.
- [ ] **Step 7: Commit** `feat(access): add departments, teams, role permissions, access scope and step-up columns`.

### Task 2: Custom-role permissions and the session contract

**Files:**
- Modify: `backend/core/src/hirevion_core/identity/permissions.py`, `identity/service.py` (`session_view`)
- Create: `backend/core/src/hirevion_core/identity/grants.py`
- Modify: `backend/api/src/hirevion_api/auth/{schemas,router}.py`
- Regenerate: `packages/api-client/openapi.json`, `packages/api-client/src/schema.d.ts`
- Modify: `recruitment-platform/src/auth/{session,permissions,dev-sessions}.ts`, `src/account/account-body.tsx`
- Tests: `backend/core/tests/test_permissions.py`, `backend/core/tests/db/test_grants.py` (new), `backend/api/tests/test_auth_api.py`, `recruitment-platform/src/auth/session.test.ts`

**Interfaces (produces):**
- `BASELINE_PERMISSIONS: tuple[str, ...] = ("account.manage",)`.
- `ASSIGNABLE_PERMISSIONS: tuple[str, ...]`: every permission not starting with `platform.`, in catalogue order.
- `permissions_for(role_keys: Iterable[str], granted: Iterable[str] = ()) -> list[str]`: the union of the baseline, the system roles' permissions and `granted`, in catalogue order. Unknown names are ignored, so a permission removed from the catalogue simply stops applying.
- `@dataclass(frozen=True) Grants(role_keys: list[str], custom_roles: list[str], permissions: list[str])` (sorted).
- `async def load_grants(session: AsyncSession, user_id: UUID) -> Grants`: one query over `user_roles ⋈ roles ⟕ role_permissions`, in the caller's tenant transaction.
- `SessionView.custom_roles: list[str]`; `SessionResponse.custom_roles: list[str]`.
- On the web, `Session.customRoles: readonly string[]` (empty for development sessions).

- [ ] **Step 1: Failing tests:**
  - **`permissions_for`:**
    - `permissions_for([])` is `["account.manage"]`;
    - `permissions_for(["interviewer"], ["jobs.view", "nonsense.perm"])` adds `jobs.view` in catalogue order and drops the unknown name.
  - **`ASSIGNABLE_PERMISSIONS`** contains no `platform.*` name, and contains every other permission.
  - **`load_grants` (db):** a user with `recruiter` plus a custom role `Sourcer` (`role_permissions`: `admin.teams.manage`) gets:
    - `role_keys == ["recruiter"]`;
    - `custom_roles == ["Sourcer"]`;
    - a permissions list that includes `admin.teams.manage`.
  - **API:** `GET /auth/session` for that user returns `custom_roles: ["Sourcer"]` and the combined permissions.
  - **Web (`session.test.ts`):** a response without `custom_roles` parses to `customRoles: []`, and one with it keeps the names.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement:**
  - `grants.py`;
  - make `AuthService.session_view` call `load_grants`;
  - in `SessionResponse`, `custom_roles: list[str] = Field(default_factory=list)`;
  - `uv run hv openapi` and `pnpm --filter @hirevion/api-codegen generate`;
  - in `session.ts`, `custom_roles: z.array(z.string()).default([])`, mapped to `customRoles`;
  - the account page lists custom role names after the translated system roles.
- [ ] **Step 4: Run** the Python tests, `uv run hv openapi --check`, `pnpm typecheck`, and `pnpm --filter @hirevion/recruitment-platform test`. All green.
- [ ] **Step 5: Commit** `feat(identity): grant custom-role permissions and report custom roles in the session`.

### Task 3: Step-up re-authentication

**Files:**
- Modify: `backend/core/src/hirevion_core/identity/{settings,sessions,service}.py`
- Modify: `backend/api/src/hirevion_api/auth/{router,schemas}.py`
- Tests: `backend/core/tests/db/test_sessions.py`, `db/test_auth_service.py`, `backend/api/tests/test_auth_api.py`

**Interfaces (produces):**
- `IdentitySettings.step_up_minutes: int = 10` (`HV_STEP_UP_MINUTES`), with a `step_up_window: timedelta` property.
- `SessionContext.stepped_up_at: datetime | None`.
- `def is_stepped_up(context: SessionContext, settings: IdentitySettings, now: datetime) -> bool`.
- `AuthService.step_up(context, password, *, ip, user_agent) -> Literal["ok", "wrong_password"] | LoginRefused`:
  - **Locked:** returns `LoginRefused(retry_after)` without checking the password.
  - **Wrong password:** records a lockout failure and the audit entry `auth.step_up.failed`, and returns `"wrong_password"`.
  - **Right password:** sets `web_sessions.stepped_up_at = now`, clears the lockout, records `auth.step_up.succeeded`, and returns `"ok"`.
- `POST /api/v1/auth/step-up` with body `{password}`:
  - success: 204;
  - wrong password: 422 `wrong-password`, with a field error on `password`;
  - locked: 429 `locked`, with `retry_after`.
- The route needs a session and CSRF, and shares sign-in's `LOGIN_BY_IP` rate rule.

- [ ] **Step 1: Failing tests:**
  - **Window:** `is_stepped_up` is false for `None`, true at 9 minutes and false at 11 minutes.
  - **Service (db):**
    - a right password sets `stepped_up_at` and audits `auth.step_up.succeeded`;
    - five wrong ones lock the email, and the sixth attempt returns `LoginRefused` even with the right password;
    - a successful sign-in afterwards, once the lock expires, still works. Use a fake clock, as `test_lockout.py` does.
  - **API:**
    - 204, then `GET /auth/session` still works;
    - 422 for a wrong password;
    - 403 `csrf-failed` without the CSRF header;
    - 401 without a session.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
  - `resolve_session` fills `stepped_up_at` from `auth_session()`.
  - The lockout key is the user's email, read in the tenant transaction.
- [ ] **Step 4: Run** the tests, `hv openapi`, codegen and the checks. All green.
- [ ] **Step 5: Commit** `feat(identity): add step-up re-authentication`.

### Task 4: The authorisation layer and the matrix test

**Files:**
- Create: `backend/api/src/hirevion_api/authz.py`
- Create: `backend/api/tests/test_authorization_matrix.py`
- Tests also: `backend/api/tests/test_authz.py` (unit, with a tiny app)

**Interfaces (produces):**
- **`Principal`** (frozen dataclass):
  - fields: `context: SessionContext`, `permissions: frozenset[str]`, `role_keys: frozenset[str]`;
  - `user_id` and `organization_id` properties;
  - `def actor(self, request: Request) -> Actor` (`Actor` comes from Task 5; add this method there).
- **`async def current_principal(request: Request, context: CurrentSession) -> Principal`:** runs `load_grants` in `db.tenant(context.organization_id)` once per request, cached on `request.state.principal`.
- **`class Requires`:**
  - `__init__(self, *permissions: str, step_up: bool = False)` takes one or more permissions, any of which grants access (a page often reads a neighbouring list). It raises `ValueError` when none are given or one isn't in `PERMISSIONS`. It exposes `.permissions: tuple[str, ...]` and `.step_up: bool`.
  - `async __call__(self, request: Request, principal: Annotated[Principal, Depends(current_principal)]) -> Principal`:
    - **No permission:** if the principal holds none of them, raises `ProblemError(403, "forbidden", "You don't have permission to do this")`.
    - **Step-up stale:** with `step_up=True` and `is_stepped_up` false, raises `ProblemError(403, "step-up-required", "Confirm your password to continue", max_age_seconds=<window>)`.
    - The permission check comes first.
- **`def requires(*permissions: str, step_up: bool = False) -> Any`:** returns `Depends(Requires(*permissions, step_up=step_up))`. Routes declare `principal: Annotated[Principal, requires("admin.users.manage")]`.
- **`UNGUARDED: dict[str, str]`:**
  - maps `"METHOD /api/v1/path"` to a reason: `"public"` (health, clock, login, forgot, reset, set-password, verify-email) or `"self"` (the signed-in user's own session, sessions, password, email, logout, step-up);
  - must list exactly today's `auth`, `health` and `clock` routes.
- **`def route_requirement(route: APIRoute) -> Requires | None`:** walks `route.dependant.dependencies` recursively and returns the first `Requires` instance found as a `call`.

- [ ] **Step 1: Failing unit tests (`test_authz.py`):**
  - `Requires("no.such")` and `Requires()` raise `ValueError`.
  - On a test app with one route guarded by `requires("admin.users.manage", step_up=True)`, with `current_principal` overridden through `app.dependency_overrides`:
    - a principal without the permission gets 403 `forbidden`, even when not stepped up;
    - one with the permission but no step-up gets 403 `step-up-required` with `max_age_seconds`;
    - one with both gets 200.
  - On a route guarded by `requires("admin.users.manage", "admin.teams.manage")`, a principal with either one gets 200.
  - `route_requirement` finds the `Requires` on that route, and returns `None` for an unguarded one.
- [ ] **Step 2: Failing matrix tests (`test_authorization_matrix.py`, `pytest -m db`):**
  - **Fixture:**
    - one organisation with a user for each of `org_admin`, `recruiter`, `hiring_manager` and `interviewer`, plus a Platform `super_admin`;
    - a session for each, created with `create_session` in its tenant, with `stepped_up_at = now()` set by the admin engine so step-up doesn't hide a 403;
    - clients carry the session and CSRF cookies, `X-CSRF-Token`, `Origin` and an `Idempotency-Key`.
  - **`test_every_route_is_classified`:** for every `APIRoute` whose path starts with `/api/v1`, assert that exactly one of these holds:
    - `route_requirement(route)` is set;
    - `f"{method} {path}"` is in `UNGUARDED`.

    Also assert that `UNGUARDED` has no entries for routes that don't exist.
  - **`test_every_guarded_route_for_every_role`** (parametrised over guarded routes × the five roles):
    - fill path parameters with random UUIDs, and send `{}` as the JSON body on POST, PUT and PATCH;
    - a role that holds none of the route's permissions gets 403 with code `forbidden`;
    - a role that holds one gets any other answer: 2xx, 403 with another code (such as `platform-organization`), 404, 409 or 422, but never `forbidden`.
    - `permissions_for([role])` gives each role's permissions.
  - **`test_every_guarded_route_needs_a_session`:** without cookies, each answers 401 `unauthenticated`.
- [ ] **Step 3: Run them.**
  - The unit tests fail (no module).
  - The matrix classification fails until `UNGUARDED` lists the existing routes; there are no guarded routes yet, so the parametrised test has no cases. This task's "failing first" is the classification test.
- [ ] **Step 4: Implement** `authz.py` and fill `UNGUARDED` from today's routes.
- [ ] **Step 5: Run** the API tests and the checks. All green.
- [ ] **Step 6: Commit** `feat(api): guard routes by permission and test every route against every role`.

### Task 5: Access core: errors, actor, audit helper and resource scope

**Files:**
- Create: `backend/core/src/hirevion_core/access/{__init__,errors,actor,audit,scope}.py`
- Create: `backend/api/src/hirevion_api/access/{__init__,errors}.py` (problem mapping), registered in `app.py`
- Tests: `backend/core/tests/test_access_errors.py`, `backend/core/tests/db/test_scope.py`, `backend/api/tests/test_access_errors_api.py`

**Interfaces (produces):**
- **`AccessError(Exception)`:**
  - `__init__(self, code: str, title: str, *, field: str | None = None, detail: str | None = None)`, with class attribute `status: ClassVar[int]`;
  - subclasses: `NotFound` (404), `Conflict` (409), `Refused` (403) and `Invalid` (422).
- **The API handler** turns an `AccessError` into `ProblemError(status, code, title, detail)`. When `field` is set, it adds a field error `{"pointer": f"#/{field}", "detail": title}` in the same format the 422 validation problems use; read `problems.py` for that format.
- **`UNSET` and `Unset`** (in `access/__init__.py`): the sentinel that tells "leave it" apart from `None` ("clear it") in update functions. Its type is `Unset`, and parameters are typed `str | None | Unset = UNSET`.
- **`def admin_role_key(organization_id: UUID) -> str`:** `"super_admin"` for the Platform organisation, otherwise `"org_admin"`. The last-admin guard counts active users holding that role.
- **`@dataclass(frozen=True) Actor`:** `user_id: UUID`, `organization_id: UUID`, `permissions: frozenset[str]`, `ip: str | None`, `user_agent: str | None`.
- **`async def record(session, actor, action, resource_type, resource_id, *, organization_id: UUID | None = None, details: Mapping[str, object] | None = None) -> None`:**
  - appends an `AuditEntry` with `actor_type="user"` and `actor_id=str(actor.user_id)` to `organization_id or actor.organization_id`;
  - platform actions pass the target organisation and add `{"via": "platform"}` to the details.
- **`@dataclass(frozen=True) ResourceScope`:** `user_id: UUID`, `organization_wide: bool`, `team_ids: frozenset[UUID]`.
- **`async def resource_scope(session: AsyncSession, user_id: UUID) -> ResourceScope`:** reads `users.access_scope`. For `teams`, it takes the user's teams, leaving out archived ones.
- **`def scope_clause(scope, *, team_column, owner_column) -> ColumnElement[bool]`:** `true()` when organisation-wide; otherwise `or_(team_column.in_(team_ids), owner_column == user_id)`, or just the owner test when the user has no teams.

- [ ] **Step 1: Failing tests:**
  - **Errors:** `Conflict("name-taken", "That name is in use", field="name")` reaches an API test app as 409, with code `name-taken` and a field error pointing at `#/name`.
  - **Scope (db):** select from a `values()` construct of five rows (team A, team B, no team owned by the user, no team owned by someone else, archived team C):
    - an `organization` user sees all five;
    - a `teams` user in A, and in the archived C, sees the A row and their own row;
    - a `teams` user with no teams sees only their own row.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement,** and add `Principal.actor(request)`.
- [ ] **Step 4: Run** the tests and the checks. All green.
- [ ] **Step 5: Commit** `feat(access): add access errors, the actor, audit helper and resource scope`.

### Task 6: Organisation profile, departments and teams

**Files:**
- Create: `backend/core/src/hirevion_core/access/{organization,structure}.py`
- Create: `backend/api/src/hirevion_api/access/{deps,schemas,organization,structure}.py`; include the routers in `app.py`
- Tests: `backend/core/tests/db/test_structure.py`, `backend/api/tests/test_structure_api.py`

**Interfaces (produces):**
- **Core functions.** All take `session: AsyncSession` (opened by the route with `db.tenant(actor.organization_id)`) and `actor: Actor`:
  - `get_profile(session, actor) -> Organization`: the Platform organisation raises `Refused("platform-organization", …)`;
  - `update_profile(session, actor, changes: ProfileChanges) -> Organization`:
    - `ProfileChanges` is a frozen dataclass of optional `name`, `website`, `country`, `timezone` and `default_locale`;
    - the Platform organisation raises `Refused("platform-organization", …)`;
    - an unknown timezone (checked against `zoneinfo.available_timezones()`) raises `Invalid("timezone", …, field="timezone")`;
    - the audit action is `organization.profile.updated`, with the changed field names only.
  - `list_departments(session, *, include_archived: bool) -> list[Department]`;
  - `create_department(session, actor, name: str, description: str | None) -> Department`:
    - the name is trimmed, 1–100 characters;
    - a duplicate raises `Conflict("name-taken", …, field="name")`;
    - the audit action is `department.created`.
  - `update_department(session, actor, department_id, *, name=UNSET, description=UNSET, archived: bool | None = None) -> Department`: audit actions `department.updated`, `department.archived` and `department.restored`.
  - `list_teams(session, *, include_archived) -> list[TeamSummary]`, where `TeamSummary` holds `team: Team`, `department_name: str | None` and `member_count: int`;
  - `create_team(session, actor, name, description, department_id)`: the department must exist and not be archived, or `Invalid(field="department_id")`;
  - `update_team(...)`, which works like `update_department` and also takes `department_id`;
  - `list_members(session, team_id) -> list[User]`;
  - `add_member(session, actor, team_id, user_id)`:
    - the team must not be archived (`Conflict("team-archived")`);
    - the user must be in this organisation (`NotFound`);
    - adding an existing member does nothing;
    - the audit action is `team.member.added`.
  - `remove_member(session, actor, team_id, user_id)`: audit action `team.member.removed`.
- **Routes:**

  | Method and path | Permission | Notes |
  |---|---|---|
  | `GET /api/v1/organization` | `admin.organization.manage` | |
  | `PATCH /api/v1/organization` | `admin.organization.manage` | |
  | `GET /api/v1/departments?include_archived=` | `admin.departments.manage` or `admin.teams.manage` | The team dialog's department picker |
  | `POST /api/v1/departments` | `admin.departments.manage` | `Idempotency-Key`, 201 |
  | `PATCH /api/v1/departments/{department_id}` | `admin.departments.manage` | |
  | `GET /api/v1/teams?include_archived=` | `admin.teams.manage` or `admin.users.manage` | The users page's team picker |
  | `POST /api/v1/teams` | `admin.teams.manage` | `Idempotency-Key`, 201 |
  | `PATCH /api/v1/teams/{team_id}` | `admin.teams.manage` | |
  | `GET /api/v1/teams/{team_id}/members` | `admin.teams.manage` | |
  | `PUT /api/v1/teams/{team_id}/members/{user_id}` | `admin.teams.manage` | 204 |
  | `DELETE /api/v1/teams/{team_id}/members/{user_id}` | `admin.teams.manage` | 204 |

- **Schemas:** `OrganizationProfileResponse` and `OrganizationProfileUpdate` (all fields optional, `extra="forbid"`); `DepartmentResponse`, `DepartmentCreate` and `DepartmentUpdate`; `TeamResponse` (with `department_name` and `member_count`), `TeamCreate` and `TeamUpdate`; `MemberResponse` (`id`, `name`, `email`, `status`).
- **Lists are small:** departments, teams and team members return plain arrays, sorted by name.
- **The Platform organisation has no profile:** `GET` and `PATCH /organization` refuse it with 403 `platform-organization`.

- [ ] **Step 1: Failing tests:**
  - **Core (db):**
    - each function's success and refusal;
    - one audit entry per change, with the right action and no extra fields;
    - archived departments and teams are hidden unless asked for;
    - a team in the archived department can still be listed.
  - **API:** the happy paths for an `org_admin` session (stepped up or not; these routes don't need step-up), plus:
    - 409 `name-taken`;
    - 422 for a bad timezone;
    - the Platform super admin is refused on `PATCH /organization`.

    The matrix test now covers these routes automatically.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, `hv openapi`, codegen and the checks. All green.
- [ ] **Step 5: Commit** `feat(access): add the organisation profile, departments and teams`.

### Task 7: Users and invitations

**Files:**
- Create: `backend/core/src/hirevion_core/access/users.py`
- Create: `backend/core/src/hirevion_core/mail/templates/{en-IN,en-US}/invitation.{subject.txt,txt,html}.j2`; add `"invitation"` to `MailTemplate` and `MAIL_TEMPLATES`
- Modify: `identity/tokens.py` (`revoke_tokens`)
- Create: `backend/api/src/hirevion_api/access/users.py`
- Tests: `backend/core/tests/db/test_users_admin.py`, `backend/core/tests/test_mail_render.py`, `backend/api/tests/test_users_api.py`

**Interfaces (produces):**
- **`async def revoke_tokens(session, *, user_id: UUID, purpose: TokenPurpose, now: datetime) -> None`:** marks every unused token for that purpose as used.
- **`@dataclass(frozen=True) UserFilters`:** `status: str | None`, `role_id: UUID | None`, `team_id: UUID | None`, `query: str | None` (matches name or email, case-insensitive).
- **`def users_statement(filters: UserFilters) -> Select[tuple[User]]`:** the API paginates it by (`User.name`, `User.id`).
- **`@dataclass(frozen=True) UserDetail`:** `user: User`, `roles: list[Role]`, `teams: list[Team]`.
- **`async def get_user(session, user_id) -> UserDetail`:** raises `NotFound("user-not-found", …)`.
- **`@dataclass(frozen=True) Invitation`:** `email`, `name`, `role_ids: list[UUID]`, `team_ids: list[UUID]`, `access_scope: str`, `locale: str`.
- **`async def invite_user(session, actor, invitation, *, settings: IdentitySettings) -> UserDetail`:**
  1. Lower-cases and trims the email. One already in use raises `Conflict("email-taken", …, field="email")`.
  2. At least one role is required: `Invalid("roles-required", field="role_ids")`.
  3. Unknown roles or teams raise `Invalid(field=…)`.
  4. Escalation guard: `Refused("escalation", …)`. The roles' permissions must all be in `actor.permissions`.
  5. Inserts the `invited` user, their `user_roles` and their `team_members` rows.
  6. Issues a `set_password` token (`settings.set_password_token_hours`).
  7. Queues the `invitation` mail. Its context is `name`, `inviter` (the actor's name), `organization`, `link` (`{web_origin}/set-password/{token}`) and `hours`.
  8. Audits `user.invited`, with the role and team ids. Never the link.
- **`async def resend_invitation(session, actor, user_id, *, settings) -> None`:** only for `invited` users, otherwise `Conflict("not-invited")`. It revokes earlier `set_password` tokens, then issues and mails a new one. Audit action `user.invitation.resent`.
- **`async def cancel_invitation(session, actor, user_id) -> None`:** only for `invited` users. Deletes the user, and the cascades remove their roles, team memberships and tokens. Audit action `user.invitation.cancelled`, with the email in the details.
- **`async def update_user(session, actor, user_id, *, name=UNSET, access_scope=UNSET, team_ids=UNSET) -> UserDetail`:**
  - `team_ids` replaces the user's memberships;
  - archived teams are refused with `Invalid(field="team_ids")`;
  - the audit action is `user.updated`, with the changed fields and the team ids before and after.
- **`async def set_roles(session, actor, user_id, role_ids: list[UUID]) -> UserDetail`:**
  - at least one role is required;
  - escalation guard as for invitations;
  - last-admin guard: if the user is the organisation's last active holder of `admin_role_key(organization_id)` and the new roles drop it, raise `Conflict("last-admin", …)`;
  - the audit action is `user.roles.changed`, with `before` and `after` as lists of `{id, name}`.
- **`async def disable_user(session, actor, user_id) -> UserDetail`:**
  - refuses the actor themselves (`Conflict("self-disable")`);
  - last-admin guard;
  - sets `status="disabled"`, revokes every session and every unused token;
  - audit action `user.disabled`.
- **`async def enable_user(session, actor, user_id) -> UserDetail`:** sets `status` to `active` when the user has a password, otherwise `invited`. Audit action `user.enabled`.
- **Routes** (all need `admin.users.manage`; step-up marked ✓):

  | Method and path | Step-up | Answer |
  |---|---|---|
  | `GET /api/v1/users` (`status`, `role_id`, `team_id`, `q`, `limit`, `cursor`) | | `Page[UserListItem]`; `admin.teams.manage` may also call it, for the members dialog's search |
  | `POST /api/v1/users` (invite; `Idempotency-Key`) | ✓ | 201 `UserResponse` |
  | `GET /api/v1/users/{user_id}` | | `UserResponse` |
  | `PATCH /api/v1/users/{user_id}` (`name`, `access_scope`, `team_ids`) | | `UserResponse` |
  | `PUT /api/v1/users/{user_id}/roles` (`{role_ids}`) | ✓ | `UserResponse` |
  | `POST /api/v1/users/{user_id}/disable` | ✓ | `UserResponse` |
  | `POST /api/v1/users/{user_id}/enable` | ✓ | `UserResponse` |
  | `POST /api/v1/users/{user_id}/invitation` (resend) | ✓ | 204 |
  | `DELETE /api/v1/users/{user_id}` (cancel an invitation) | ✓ | 204 |

  - **`UserListItem`:** `id`, `name`, `email`, `status`, `access_scope`, `roles: list[RoleRef]`, `teams: list[TeamRef]`, `created_at`.
  - **`UserResponse`** is the same as `UserListItem`.
  - **`RoleRef`:** `{id, key, name}`. **`TeamRef`:** `{id, name}`.
- **Templates:** subject "You're invited to {organization} on Hirevion" in both locales. Copy the existing templates' layout. The body names the inviter, the organisation, the link and its expiry in hours.

- [ ] **Step 1: Failing tests:**
  - **Core (db), one test per rule above:**
    - invite → user `invited`, roles and teams set, exactly one `mail` outbox event with template `invitation`, and an audit entry that has no `link`;
    - the invitation link works with SP-02a's `set_password`: the user becomes `active` and can sign in;
    - a resend makes the first link invalid;
    - a cancel removes the user, so the email can be invited again;
    - `email-taken` (also across organisations), `roles-required` and `escalation`. For escalation, a custom role holding `admin.users.manage` tries to invite with `org_admin`.
    - `last-admin` on both `set_roles` and `disable_user`, and `self-disable`;
    - disable → that user's existing session no longer resolves; enable restores the status.
  - **Rendering:** the invitation renders in both locales, with the link in both the text and HTML parts.
  - **API:**
    - the filters and pagination of `GET /users`;
    - each route's success;
    - `step-up-required` on the step-up routes when `stepped_up_at` is old;
    - the problem codes above.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, `hv openapi`, codegen and the checks. All green, including the matrix test.
- [ ] **Step 5: Commit** `feat(access): add user administration and email invitations`.

### Task 8: Custom roles and the permission catalogue

**Files:**
- Create: `backend/core/src/hirevion_core/access/roles.py`
- Create: `backend/api/src/hirevion_api/access/roles.py`
- Tests: `backend/core/tests/db/test_roles_admin.py`, `backend/api/tests/test_roles_api.py`

**Interfaces (produces):**
- **`@dataclass(frozen=True) RoleSummary`:** `role: Role`, `permissions: list[str]` (code for system roles, stored for custom ones, plus the baseline, in catalogue order), `member_count: int`.
- **`async def list_roles(session) -> list[RoleSummary]`:** system roles first in `SYSTEM_ROLE_NAMES` order, then custom roles by name.
- **`async def create_role(session, actor, *, name: str, description: str | None, permissions: list[str]) -> RoleSummary`:**
  - the name is trimmed, 1–60 characters, and unique per organisation including system names (`Conflict("name-taken", field="name")`);
  - the permissions must be in `ASSIGNABLE_PERMISSIONS` (`Invalid("unknown-permission", field="permissions")`) and in `actor.permissions` (`Refused("escalation")`);
  - the audit action is `role.created`, with the permissions.
- **`async def update_role(session, actor, role_id, *, name=UNSET, description=UNSET, permissions=UNSET) -> RoleSummary`:**
  - system roles raise `Conflict("role-system", …)`;
  - same rules as `create_role`;
  - the audit action is `role.updated`, with `added` and `removed` permissions.
- **`async def delete_role(session, actor, role_id) -> None`:**
  - system roles raise `Conflict("role-system")`;
  - a role with members raises `Conflict("role-in-use", …)`, whose `detail` gives the count;
  - the audit action is `role.deleted`.
- **Routes:**

  | Method and path | Permission | Step-up | Notes |
  |---|---|---|---|
  | `GET /api/v1/roles` | `admin.roles.manage` or `admin.users.manage` | | `list[RoleResponse]`: `id`, `key`, `name`, `description`, `system`, `permissions`, `member_count`; it feeds the users page's role picker too |
  | `POST /api/v1/roles` | `admin.roles.manage` | ✓ | `Idempotency-Key`, 201 |
  | `PATCH /api/v1/roles/{role_id}` | `admin.roles.manage` | ✓ | |
  | `DELETE /api/v1/roles/{role_id}` | `admin.roles.manage` | ✓ | 204 |
  | `GET /api/v1/permissions` | `admin.roles.manage` | | `list[PermissionResponse]` `{name, area}` over `ASSIGNABLE_PERMISSIONS`; `area` is the text before the first dot |

- **Assigning roles needs only `admin.users.manage`** (Task 7), because assignment is user administration; defining roles needs `admin.roles.manage`.

- [ ] **Step 1: Failing tests:**
  - **Core (db):**
    - create, update and delete, each audited with the right details;
    - a member of a custom role gains a permission on their next `load_grants`, with no new sign-in;
    - `role-system`, `role-in-use`, `name-taken` (`Recruiter` vs `recruiter`), `unknown-permission` (`platform.view`) and `escalation`.
  - **API:**
    - the routes;
    - `GET /roles` is allowed for `admin.users.manage` alone;
    - `GET /permissions` lists no `platform.*` name.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, `hv openapi`, codegen and the checks. All green.
- [ ] **Step 5: Commit** `feat(access): add custom roles and the permission catalogue`.

### Task 9: Platform organisations

**Files:**
- Create: `backend/core/src/hirevion_core/access/platform.py`
- Create: `backend/api/src/hirevion_api/access/platform.py`
- Tests: `backend/core/tests/db/test_platform_admin.py`, `backend/api/tests/test_platform_api.py`

**Interfaces (produces):**
- **`@dataclass(frozen=True) OrganizationListing`:** `id`, `name`, `slug`, `status`, `created_at`, `user_count`.
- **`async def list_organizations(session, *, query: str | None, status: str | None, after: tuple[str, UUID] | None, limit: int) -> list[OrganizationListing]`:**
  - selects from `platform_organizations()`;
  - `query` matches name or slug, case-insensitively;
  - ordered by (`name`, `id`), with keyset paging on them;
  - the API encodes the cursor with `encode_cursor` and `decode_cursor` from `pagination.py`.
- **One transaction per platform action.** The route opens `db.tenant(PLATFORM_ORGANIZATION_ID)` (where the idempotency record lives too). Each function below then:
  1. calls `switch_tenant(target)`;
  2. makes its changes and records them in the target's chain;
  3. calls `switch_tenant(PLATFORM_ORGANIZATION_ID)` and records the same action in the platform chain.

  So both chains, the change and the idempotency record commit together. **Every function returns with the session switched back to the Platform tenant.**
- **`async def create_organization(session, actor, *, name: str, slug: str, admin_name: str, admin_email: str, settings: IdentitySettings) -> OrganizationListing`:**
  - **Slug:** must match `^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$`. Reserved slugs (`platform`, `admin`, `api`, `app`, `www`) raise `Invalid(field="slug")`. A slug in use raises `Conflict("slug-taken", field="slug")`.
  - **Steps:**
    1. Generates `new_id = uuid7()` and calls `switch_tenant(new_id)`.
    2. Inserts the organisation.
    3. Runs `ensure_system_roles`.
    4. Invites the first admin, with the `org_admin` role. Call a shared helper extracted from `invite_user`: `_create_invitation(session, organization_id, inviter_name, …)`, without the escalation guard, because the super admin acts as the platform.
    5. Records `platform.organization.created` in both chains.
- **`async def set_organization_status(session, actor, organization_id, *, suspended: bool, reason: str | None) -> OrganizationListing`:**
  - the Platform organisation raises `Conflict("platform-organization")`;
  - **on suspension,** sets `status`, revokes every session of the organisation's users, and records `platform.organization.suspended` (with the reason) in both chains;
  - **on reactivation,** records `platform.organization.reactivated` in both chains.
- **`async def invite_organization_admin(session, actor, organization_id, *, name, email, settings) -> None`:** another `org_admin` invitation, for when the first one lapsed. Records `platform.organization.admin_invited` in both chains.
- **Routes** (all need `platform.organizations.manage`):

  | Method and path | Step-up | Notes |
  |---|---|---|
  | `GET /api/v1/platform/organizations` (`q`, `status`, `limit`, `cursor`) | | |
  | `POST /api/v1/platform/organizations` | ✓ | `Idempotency-Key`, 201 |
  | `POST /api/v1/platform/organizations/{organization_id}/suspend` (`{reason}`) | ✓ | |
  | `POST /api/v1/platform/organizations/{organization_id}/reactivate` | ✓ | |
  | `POST /api/v1/platform/organizations/{organization_id}/admins` (`{name, email}`) | ✓ | 204 |

  The create's idempotency record is stored under the Platform organisation, with scope `user:<super admin id>`, in the same transaction.

- [ ] **Step 1: Failing tests:**
  - **Core (db):**
    - creating gives an organisation with its four system roles and an invited admin with `org_admin`, plus an invitation in the outbox;
    - the create entry is in both audit chains, and `AuditService.verify_chain` passes for both;
    - suspension ends an existing session of that organisation and blocks sign-in (`LoginRefused`); reactivation restores sign-in;
    - the Platform organisation can't be suspended;
    - `slug-taken` and the reserved slugs;
    - the listing pages through 3 organisations two at a time.
  - **API:** each route; an `org_admin` gets 403 `forbidden` (the matrix covers it too).
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, `hv openapi`, codegen and the checks. All green.
- [ ] **Step 5: Commit** `feat(access): let super admins create, suspend and reactivate organisations`.

### Task 10: Web foundation: API calls, step-up, permission labels and the dev notice

**Files:**
- Create: `recruitment-platform/src/admin/api.ts`, `src/admin/step-up.tsx`, `src/admin/dev-notice.tsx`, `src/admin/permission-label.ts`
- Modify: `recruitment-platform/src/app/recruiter/(shell)/layout.tsx` (mount `StepUpProvider`)
- Modify: `messages/en-IN.json`, `messages/en-US.json` (`stepUp`, `permissionLabels`, `admin.common`)
- Tests: `src/admin/step-up.test.tsx`, `src/admin/permission-label.test.ts`, `src/admin/api.test.ts`

**Interfaces (produces):**
- **`src/admin/api.ts`:** typed wrappers over `apiClient()`, one per route in Tasks 6–9, named after the action:
  - organisation and structure: `getOrganization`, `updateOrganization`, `listDepartments`, `createDepartment`, `updateDepartment`, `listTeams`, `createTeam`, `updateTeam`, `listTeamMembers`, `addTeamMember`, `removeTeamMember`;
  - users: `listUsers`, `inviteUser`, `getUser`, `updateUser`, `setUserRoles`, `disableUser`, `enableUser`, `resendInvitation`, `cancelInvitation`;
  - roles: `listRoles`, `createRole`, `updateRole`, `deleteRole`, `listPermissions`;
  - platform: `listOrganizations`, `createOrganization`, `suspendOrganization`, `reactivateOrganization`, `inviteOrganizationAdmin`.

  Creates send `Idempotency-Key: crypto.randomUUID()`, generated once per form submission and reused on retry. The types come from `components["schemas"][…]`.
- **`StepUpProvider` and `useStepUp()`:**
  - `useStepUp()` returns `<T>(call: () => Promise<T>) => Promise<T>`.
  - When `call` rejects with an `ApiProblem` whose code is `step-up-required`, it opens a dialog: "Confirm your password", with a password field (`autocomplete="current-password"`), Confirm and Cancel.
  - On Confirm it POSTs `/api/v1/auth/step-up`, then retries `call` once.
  - A wrong password shows the field error and keeps the dialog open. A 429 shows the lockout message. Cancel rejects with the original problem.
- **`permissionLabelKey(permission: string): string`:** `permission.replaceAll(".", "_")`, because next-intl treats dots as nesting. `permissionLabels` in both catalogues has a key for every permission in the web's `PERMISSIONS` list. An area's heading key is `permissionAreas.<area>`.
- **`AdminDevNotice`:** the account page's development-session empty state, worded for administration: "Sign in with a real account to manage this".

- [ ] **Step 1: Failing tests:**
  - **`step-up.test.tsx`:**
    - the first call rejects with `step-up-required`; the dialog appears and the password is posted (fetch faked); the call is retried and its result returned;
    - a wrong password (422) keeps the dialog open with the error;
    - Cancel rejects;
    - an axe check of the open dialog.
  - **`permission-label.test.ts`:**
    - every permission in `PERMISSIONS` has a label in both catalogues;
    - every area has a heading;
    - there are no labels for unknown permissions.
  - **`api.test.ts`:** `inviteUser` sends an `Idempotency-Key` and the CSRF header, and reuses the key when given one.
- [ ] **Step 2: Run** `pnpm --filter @hirevion/recruitment-platform test`; the new tests fail.
- [ ] **Step 3: Implement,** and mount `StepUpProvider` in the shell layout.
- [ ] **Step 4: Run** `pnpm lint`, `pnpm typecheck` and `pnpm test`. All green.
- [ ] **Step 5: Commit** `feat(web): add admin API calls, the step-up dialog and permission labels`.

### Task 11: Web: the users and roles pages

**Files:**
- Create: `recruitment-platform/src/admin/users/{users-body,users-table,invite-dialog,user-sheet}.tsx`
- Create: `recruitment-platform/src/admin/roles/{roles-body,role-editor,permission-matrix}.tsx`
- Modify: `src/app/recruiter/(shell)/admin/{users,roles}/page.tsx` (`guardedPage(path, Body)`)
- Modify: messages (`admin.users`, `admin.roles`)
- Tests: `src/admin/users/*.test.tsx`, `src/admin/roles/*.test.tsx`

**Behaviour:**
- **Users page** (`UsersBody`):
  - **Development sessions** see `AdminDevNotice`.
  - **The table** (`DataTable`, `useCursorPage`, filters in the URL via `useUrlTableState`):
    - columns: name with email, roles, teams, status as a badge, access;
    - filters: status, role, team, and a search box;
    - "Invite user" opens `InviteDialog`.
  - **`InviteDialog`:**
    - fields: email, name, roles (checkbox list from `listRoles`, at least one), teams (from `listTeams`), access (two radio options, "The whole organisation" or "Only their teams' work"), language;
    - it submits through `useStepUp`;
    - a problem's field errors land on the matching fields (`fieldErrors`).
  - **Clicking a row** opens `UserSheet` (a `Dialog` laid out as a side sheet). It edits name, access and teams (`PATCH`) and roles (`PUT …/roles`, through step-up), and shows Disable or Enable (step-up). For invited users it shows "Resend invitation" and "Cancel invitation".
  - **Problems** `last-admin`, `self-disable` and `escalation` show as translated toasts.
- **Roles page** (`RolesBody`):
  - **Development sessions** see `AdminDevNotice`.
  - **The role list:** system roles marked "Built in" and read-only; custom roles with member counts. "New role" opens `RoleEditor`.
  - **`RoleEditor`:** name, description, and the permissions grouped by area as checkboxes. Permissions the signed-in user doesn't hold are disabled, with the hint "You can't grant what you don't have". Saving goes through step-up; Delete is shown when the role has no members.
  - **`PermissionMatrix`:** a read-only table with a row per permission (grouped by area with row headers) and a column per role, marked ✓ or —. Each cell has text for screen readers ("Granted" or "Not granted"). It's the PRD's "permission matrix UI".

- [ ] **Step 1: Failing component tests** (Vitest with jsdom and a faked API module):
  - the users table renders rows and moves filters into the URL;
  - the invite dialog validates email and roles, submits, and closes on success;
  - a 409 `email-taken` marks the email field;
  - the user sheet shows Resend and Cancel only for invited users;
  - the role editor disables permissions the user lacks, and blocks system roles;
  - the matrix has row and column headers, and cell text for screen readers;
  - an axe check of each open dialog.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement,** and wire the pages.
- [ ] **Step 4: Run** `pnpm lint`, `pnpm typecheck` and `pnpm test`, then the web-mode Playwright suite (`pnpm --filter @hirevion/recruitment-platform e2e`). The admin pages show the dev notice there and pass axe in both themes.
- [ ] **Step 5: Commit** `feat(web): add the users and roles pages`.

### Task 12: Web: organisation, departments, teams and platform organisations

**Files:**
- Create: `recruitment-platform/src/admin/organization/organization-body.tsx`
- Create: `recruitment-platform/src/admin/structure/{departments-body,teams-body,team-members-dialog}.tsx`
- Create: `recruitment-platform/src/platform/organizations/{organizations-body,create-organization-dialog}.tsx`
- Modify: the four `page.tsx` files, and messages (`admin.organization`, `admin.departments`, `admin.teams`, `platform.organizations`)
- Tests: the matching `*.test.tsx`

**Behaviour:**
- **Organisation:**
  - a profile form: name; website; country (a select of ISO codes with `Intl.DisplayNames` names); time zone (a searchable select of `Intl.supportedValuesOf("timeZone")`); default language;
  - Save is enabled once something changes;
  - super admins belong to the Platform organisation, which has no profile, so they see an empty state that links to Platform → Organisations (`session.organization === null`).
- **Departments:**
  - a table of name, description and team count, with a "Show archived" switch;
  - Create and Edit in a dialog, and Archive or Restore from the row menu.
- **Teams:**
  - a table of name, department, members and description, with "Show archived";
  - a create or edit dialog that includes the department;
  - "Members" opens `TeamMembersDialog`: the member list with Remove, and an add field that searches `listUsers({q})`.
- **Platform organisations:**
  - a table of name, slug, status, users and created date, with a status filter and search;
  - "New organisation" asks for name, slug (suggested from the name), and the first admin's name and email, through step-up;
  - the row menu offers Suspend (with a reason), Reactivate and "Invite another admin", all through step-up;
  - the Platform row has no menu.
- **Development sessions** see `AdminDevNotice` on all four pages.

- [ ] **Step 1: Failing component tests:**
  - the profile form submits only the changed fields;
  - a super admin (Platform organisation) sees an empty state pointing to Platform → Organisations instead of the form;
  - the department and team dialogs validate and submit;
  - archiving moves a row out of the default view;
  - the members dialog adds and removes;
  - the create-organisation dialog suggests the slug and shows `slug-taken` on the field;
  - suspend asks for a reason;
  - an axe check of each dialog.
- [ ] **Step 2: Run them;** they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pnpm lint`, `pnpm typecheck` and `pnpm test`, then web-mode Playwright. All green.
- [ ] **Step 5: Commit** `feat(web): add the organisation, departments, teams and platform organisation pages`.

### Task 13: End to end, seed data, docs and finish

**Files:**
- Create: `recruitment-platform/e2e/auth/admin.spec.ts`; extend `e2e/auth/support.ts`
- Modify: `tools/devcli/src/hirevion_devcli/identity.py`, `hirevion_core/identity/bootstrap.py` (`seed_identity` adds a department "Engineering" and a team "Platform hiring" with the seeded recruiter in it)
- Create: `docs/architecture/adr/0014-organizations-and-access.md`; update the ADR index
- Modify: `docs/runbooks/local-dev.md` ("Sign in locally" gains the admin pages, step-up and `HV_STEP_UP_MINUTES`), `MASTER_IMPLEMENTATION_PLAN.md` §7 (replace `user_invitations` with "invitations are `invited` users plus a set-password token (ADR-0014)")
- Tests: `backend/core/tests/db/test_bootstrap.py`

**`admin.spec.ts`** (auth mode, real API and Mailpit; every account it creates is fresh, so the seeded users stay as they are):
1. **The organisation admin invites a recruiter:**
   - signs in as `org-admin@acme.example.test` and goes to `/admin/users`;
   - Invite user, with a fresh email and the Recruiter role;
   - the step-up dialog appears; they enter the password, and the invitation is sent;
   - the invitee opens the emailed `/set-password/…` link, sets a password and signs in;
   - they see Jobs in the navigation and no Administration.
2. **A custom role:**
   - the admin creates a role "Talent sourcer" with `jobs.view` and `admin.teams.manage`, and assigns it as the only role of a fresh invited and activated user;
   - that user can open `/admin/teams` but gets the forbidden page at `/admin/users`;
   - the admin removes `admin.teams.manage`, and the user's next visit to `/admin/teams` is forbidden, without signing in again.
3. **Disabling:** the admin disables a fresh user who is signed in elsewhere. That browser's next navigation goes to `/login`.
4. **Platform:**
   - the super admin (`super@hirevion.example.test`) creates an organisation with a fresh slug and first admin; the admin accepts from Mailpit and signs in;
   - the super admin suspends the organisation, and the admin's next navigation goes to `/login`, where signing in is refused;
   - reactivating lets them sign in again.

**Steps:**
- [ ] **Step 1: Write `admin.spec.ts`.** Run it against `uv run hv api` with `HV_E2E_API=1` and `FORCE_COLOR=1`. It fails until every page works end to end; fix what it finds, with a failing unit test first for each bug.
- [ ] **Step 2: Seed data.** The failing `test_bootstrap.py` case: `seed_identity` creates the department and team once, and a second run changes nothing. Then implement it.
- [ ] **Step 3: Docs.**
  - **ADR-0014** records the six decisions above, plus:
    - the `Requires` and `UNGUARDED` rule and the matrix test;
    - the escalation and last-admin guards;
    - step-up;
    - platform functions and `switch_tenant`.

    Its Consequences cover:
    - SP-04 and SP-07 apply `scope_clause`;
    - SP-19 adds MFA to step-up;
    - SP-22's audit-log page reads these actions.
  - **The runbook and master plan** as listed above.
- [ ] **Step 4: Full gate:**
  - Python: `uv run ruff check .`, `ruff format --check .`, mypy (CI's command), `uv run hv openapi --check`, `uv run pytest backend tools`;
  - web: `pnpm lint`, `pnpm typecheck`, `pnpm test`;
  - both Playwright modes.
- [ ] **Step 5: Commit** in three parts:
  - `test(web): add the admin end-to-end suite`;
  - `feat(devcli): seed a department and a team`;
  - `docs: add ADR-0014 organisations and access`.
- [ ] **Step 6: Finish:** push the branch, watch CI until every job is green, fast-forward `main`, push it, delete the branch locally and on GitHub, and update the progress memory.

## Self-review

- **Spec coverage (SP-02b list):**

  | Spec item | Tasks |
  |---|---|
  | Super-admin create and suspend for organisations | 9, 12 |
  | Organisation profile, departments, teams | 6, 12 |
  | Users | 7, 11 |
  | Email invitations | 7, 11, 13 |
  | Custom roles and the permission matrix UI | 2, 8, 11 |
  | Resource scoping | 1, 5 (rule), 7 (setting), 11 (UI); SP-04 and SP-07 apply it |
  | Step-up re-authentication for role changes | 3, 4, 7–9, 10 |
  | Auditing of permission changes | 6–9 |
  | Admin and platform pages | 11, 12 |
  | Authorisation-matrix test | 4 (grows with every route) |
  | Tenant-isolation suite over new tables | 1 |
  | Playwright | 13 |

- **Master plan §14 SP-02 exit criteria:**
  - the authorisation matrix: Task 4;
  - the tenant-isolation suite: Task 1;
  - the Playwright authentication tests: SP-02a plus Task 13.
- **Types are named consistently:**
  - `Actor`, `UNSET` and `admin_role_key` (Task 5) are used in Tasks 6–9;
  - `Requires` takes any-of permissions from Task 4, used by Tasks 6–8's list routes;
  - every core function takes `session` first, including the platform ones (Task 9), which switch tenants inside it;
  - `load_grants` (Task 2) is used by `current_principal` (Task 4);
  - `switch_tenant` (Task 1) is used in Task 9;
  - `revoke_tokens` (Task 7) is used by `disable_user`.
