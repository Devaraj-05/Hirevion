# SP-02a Accounts and Sign-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real sign-in for the Recruitment Platform, as specified in `docs/superpowers/specs/2026-10-01-sp-02-identity-access-design.md`. It covers:
- users and the reserved Platform organisation;
- password sign-in and sign-out with server-side sessions;
- password reset and email verification, with emails through the outbox;
- the breached-password check, lockout and rate limits;
- the session list;
- `GET /api/v1/auth/session` in ADR-0012's contract;
- the sign-in, password and account pages.

**Architecture:**

- **`hirevion_core.identity`** holds the domain:
  - password policy and hashing, and the breach check;
  - the permission catalogue and system roles;
  - sessions, tokens and lockout;
  - `AuthService`.
- **The sign-in lookup.** Two `SECURITY DEFINER` functions owned by a `NOLOGIN` role, `hirevion_auth`, find a user by email and a session by token hash before the organisation is known. Everything else runs in `db.tenant(org)` under ADR-0009's forced row-level security.
- **`hirevion_api.auth`** adds:
  - the session dependency;
  - the CSRF and Origin checks;
  - the `/api/v1/auth/*` router.
- **Email.** `hirevion_core.mail` renders emails, which travel outbox → relay → the `mail` stream → a consumer → SMTP. The relay and the consumer run as background tasks in the API process.
- **The web app** gets the forms and the account page. In `next dev` it proxies `/api/*` to the API.

**Tech Stack:**
- **Existing:** FastAPI, SQLAlchemy 2 async, Alembic, asyncpg, redis-py and aiohttp; Next 16, next-intl and TanStack Query; Playwright 1.63.0.
- **New** (pinned through uv's lock): argon2-cffi 25.x (MIT), Jinja2 3.x (BSD-3), aiosmtplib 4.x (MIT). Each must be at least a day old (the repo's release-age rule).
- **Common-passwords list:** SecLists, MIT licence.

## Global Constraints

- **Master plan §13 applies to every task:**
  - UUIDv7 keys and UTC `timestamptz`;
  - `organization_id` and forced row-level security on every tenant table;
  - RFC 9457 problems, cursor pagination and `Idempotency-Key` on creates;
  - every string externalised (en-IN and en-US);
  - WCAG 2.2 AA;
  - TDD;
  - at least 85% line coverage on domain modules;
  - every auth path tested.
- **Secrets never appear in logs, problems, audit details or test output:** passwords, password hashes, session tokens, reset and verification tokens. Store tokens as SHA-256 only.
- **Answers that would reveal whether an account exists are identical:** login failure, `password/forgot`, and lockout's message.
- **Sessions:**
  - `__Host-hv_session`: Secure, HttpOnly, SameSite=Lax, Path=/;
  - 30 minutes idle and 12 hours absolute;
  - rotated at sign-in.
- **CSRF:** a state-changing request with a session cookie needs `X-CSRF-Token` equal to the `__Host-hv_csrf` cookie, and an allowed `Origin`.
- **Passwords:** 15–128 characters after NFKC; no composition rules; not breached or common; not the email, name or organisation name; argon2id.
- **The web app** keeps its development sessions (`hv_dev_role`); the route × role Playwright suite keeps running without an API.
- **Git:** commit as Devaraj-05 only, with no AI attribution (CLAUDE.md).

## File Structure

| Path | Responsibility |
|---|---|
| `backend/migrations/versions/0006_identity.py` | `hirevion_auth` role, Platform organisation, `users`, `web_sessions`, `auth_tokens`, `roles`, `user_roles`, policies, lookup functions |
| `backend/core/src/hirevion_core/models/{user,web_session,auth_token,role}.py` | ORM models |
| `backend/core/src/hirevion_core/db/isolation.py` | Also audits `hirevion_auth` |
| `backend/core/src/hirevion_core/identity/permissions.py` | `PERMISSIONS`, `SYSTEM_ROLES`, `permissions_for(role_keys)` |
| `backend/core/src/hirevion_core/identity/passwords.py` | `PasswordPolicy`, `hash_password`, `verify_password`, `DUMMY_HASH` |
| `backend/core/src/hirevion_core/identity/breach.py` | `BreachChecker`, `LocalListChecker`, `HibpChecker`, `CompositeChecker` |
| `backend/core/src/hirevion_core/identity/data/common-passwords.txt` | SecLists top-100k, entries of 8+ characters, lower-cased |
| `backend/core/src/hirevion_core/identity/sessions.py` | `create_session`, `resolve_session`, `revoke_*`, `SessionContext` |
| `backend/core/src/hirevion_core/identity/tokens.py` | `issue_token`, `consume_token` (`auth_tokens`) |
| `backend/core/src/hirevion_core/identity/lockout.py` | `Lockout` (Valkey) |
| `backend/core/src/hirevion_core/identity/service.py` | `AuthService` |
| `backend/core/src/hirevion_core/identity/settings.py` | `IdentitySettings` (`HV_SESSION_*`, `HV_HIBP_ENABLED`, `HV_WEB_ORIGIN`) |
| `backend/core/src/hirevion_core/mail/{settings,render,sender,consumer,runner}.py`, `mail/templates/{en-IN,en-US}/*.{txt,html}.j2` | Email |
| `backend/api/src/hirevion_api/auth/{deps,csrf,router,schemas}.py` | API |
| `backend/api/src/hirevion_api/app.py`, `settings.py` | Wiring, `HV_API_ALLOWED_ORIGINS`, `HV_API_RUN_WORKERS` |
| `tools/devcli/src/hirevion_devcli/{identity,cli}.py` | `create-super-admin`, `seed-identity`, `worker` |
| `recruitment-platform/src/auth/*`, `src/app/recruiter/(auth)/**`, `src/app/recruiter/(shell)/account/**`, `src/account/**` | Pages, forms, sign-out |
| `recruitment-platform/e2e/auth/*.spec.ts`, `playwright.config.ts` | The `auth` project (real API) |
| `.github/workflows/ci.yml` | Mailpit in `python`; new `e2e-auth` job |
| `docs/architecture/adr/0013-sign-in-and-sessions.md`, `docs/runbooks/local-dev.md` | Docs |

---

### Task 1: Identity tables, the Platform organisation and the lookup functions

**Files:**
- Create: `backend/migrations/versions/0006_identity.py`
- Create: `backend/core/src/hirevion_core/models/{user,web_session,auth_token,role}.py`
- Modify: `models/__init__.py`, `db/isolation.py`
- Tests: `backend/core/tests/db/test_identity_schema.py`; `test_isolation.py`; `test_models_match_migrations.py` (already compares every model)

**Interfaces (produces):**
- `PLATFORM_ORGANIZATION_ID = UUID("00000000-0000-7000-8000-000000000001")` in `hirevion_core.identity` (`identity/__init__.py`).
- `AUTH_ROLE = "hirevion_auth"` in `hirevion_core.settings`.
- **Models:**
  - **`User`:** `id`, `organization_id`, `email` (citext, unique), `name`, `locale`, `status` (`invited|active|disabled`), `password_hash`, `email_verified_at`, `password_changed_at`, `created_at`, `updated_at`.
  - **`WebSession`:** `id`, `organization_id`, `user_id`, `token_hash` (bytea, unique), `csrf_hash` (bytea), `created_at`, `last_seen_at`, `expires_at`, `ip` (inet), `user_agent`, `revoked_at`.
  - **`AuthToken`:** `id`, `organization_id`, `user_id`, `purpose` (`set_password|reset_password|verify_email`), `token_hash` (bytea, unique), `new_email`, `expires_at`, `used_at`, `created_at`.
  - **`Role`:** `id`, `organization_id`, `key` (system key or null), `name`, `system` (bool); unique (`organization_id`, `key`).
  - **`UserRole`:** `organization_id`, `user_id`, `role_id`; primary key (`user_id`, `role_id`).
  - Foreign keys are composite with `organization_id` where the referenced table has it (master plan §7).
- **SQL functions** (`STABLE SECURITY DEFINER SET search_path = public, pg_temp`):
  - `auth_user_by_email(p_email citext)` returns table (`user_id`, `organization_id`, `status`, `password_hash`, `organization_status`).
  - `auth_session(p_token_hash bytea)` returns table (`session_id`, `user_id`, `organization_id`, `csrf_hash`, `last_seen_at`, `expires_at`, `revoked_at`, `user_status`, `organization_status`).

- [ ] **Step 1: Failing tests** (`pytest -m db`):
  - The isolation harness reports no problems, and now also checks that `hirevion_auth`:
    - can't log in;
    - doesn't bypass row-level security;
    - owns no tables.
  - As `hirevion_app` in organisation A's tenant: `SELECT FROM users` sees only A's users, and inserting a user for organisation B fails.
  - As `hirevion_app` with no tenant: `auth_user_by_email('A-user@example.test')` returns A's user and organisation status. Email matching ignores case.
  - `auth_session(hash)` returns the session joined with its user and organisation status, and an unknown hash returns no rows.
  - `hirevion_app` can't `SELECT` directly from the functions' underlying data without a tenant (zero rows).
  - `hirevion_app` holds `EXECUTE` on the two functions only; `PUBLIC` holds none.
  - The Platform organisation exists, with slug `platform`, and has a `super_admin` system role.
  - Two users can't share an email across organisations (unique violation).
- [ ] **Step 2: Run them** and watch them fail (no tables).
- [ ] **Step 3: Write the migration:**
  ```python
  op.execute("""
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hirevion_auth') THEN
      CREATE ROLE hirevion_auth NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
  END $$""")
  ```
  - **Tables:** create the five tables with the columns above. For each, apply `tenant_policy_sql(...)` and `grant_sql(..., ["SELECT","INSERT","UPDATE"])` (`DELETE` too on `user_roles`).
  - **The lookup role's access:** for `users`, `organizations` and `web_sessions`:
    ```sql
    GRANT SELECT ON <t> TO hirevion_auth;
    CREATE POLICY <t>_auth_lookup ON <t> FOR SELECT TO hirevion_auth USING (true);
    ```
  - **The functions:** create both, then `ALTER FUNCTION … OWNER TO hirevion_auth`, `REVOKE ALL ON FUNCTION … FROM PUBLIC` and `GRANT EXECUTE ON FUNCTION … TO hirevion_app`.
  - **Seeding:** insert the Platform organisation and its `super_admin` role with the fixed ids.
  - **Downgrade:** drop everything in reverse; the role stays, since roles are cluster-wide.
- [ ] **Step 4: Write the models** and add `AUTH_ROLE` to the isolation harness's checks. The existing check already covers any table with `organization_id`.
- [ ] **Step 5: Run** `uv run pytest backend -m db` (all green), then `uv run ruff check`, `uv run ruff format --check` and `uv run pyright`.
- [ ] **Step 6: Commit** `feat(identity): add users, sessions, tokens and roles with the sign-in lookup functions`.

### Task 2: Passwords: policy, hashing and the breach check

**Files:**
- Create: `identity/passwords.py`, `identity/breach.py`, `identity/data/common-passwords.txt`, `identity/data/README.md` (source, licence and filter)
- Modify: `backend/core/pyproject.toml` (`uv add --package hirevion-core argon2-cffi`)
- Tests: `backend/core/tests/test_passwords.py`, `test_breach.py`

**Interfaces (produces):**
- `PasswordProblem = Literal["too_short","too_long","personal","common","breached"]`.
- `class PasswordPolicy`: `min_length: int = 15`, `max_length: int = 128`, and `async def check(self, password: str, *, email: str, name: str, organization: str) -> list[PasswordProblem]`. It takes a `BreachChecker`.
- `hash_password(password: str) -> str`.
- `verify_password(stored: str | None, password: str) -> tuple[bool, bool]` returns (valid, needs_rehash). A `None` stored hash verifies against `DUMMY_HASH` and returns `(False, False)`.
- `class BreachChecker(Protocol)`: `async def is_breached(self, password: str) -> bool`.
- `LocalListChecker.from_package()`.
- `HibpChecker(fetch: Callable[[str], Awaitable[str]], timeout: float = 2.0)`, with `aiohttp_range_fetcher(session) -> fetch`.
- `CompositeChecker(local, remote | None)`.

- [ ] **Step 1: Failing tests:**
  - 14 characters is `too_short`, and 129 is `too_long`. Length counts code points after NFKC, so `"ﬁ"*8` is 16.
  - A password containing the email's local part, the name or the organisation name (case-insensitive, 4+ characters) is `personal`.
  - **Local list:** a list entry with different case (`"Password123456789"`) is `common`.
  - **HIBP:**
    - the fake fetch receives the upper-cased 5-character prefix;
    - a suffix line with a count above 0 is `breached`;
    - padding lines (count 0) are ignored.
  - **HIBP failures:** when the fetch raises or exceeds the timeout, `CompositeChecker` returns the local result and logs one warning without the password or hash. Check this with caplog.
  - **The real fetcher** against an aiohttp `TestServer`: path `/range/ABCDE`, header `Add-Padding: true`, and a `User-Agent` set.
  - **Hashing:**
    - `hash_password` returns `$argon2id$`;
    - `verify_password` accepts the right password and refuses the wrong one;
    - a hash with lower parameters reports `needs_rehash`;
    - `verify_password(None, …)` returns `(False, False)` and still takes argon2 time (it calls `DUMMY_HASH`).
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Build the list:**
  - download SecLists `Passwords/Common-Credentials/10-million-password-list-top-100000.txt`;
  - keep entries of 8 or more characters, lower-cased and de-duplicated;
  - commit the file with `README.md` naming the source URL, the commit and the MIT licence.
- [ ] **Step 4: Implement:**
  - `PasswordHasher()` from argon2-cffi with its defaults (RFC 9106 low-memory profile);
  - `unicodedata.normalize("NFKC", …)` before every check and hash.
- [ ] **Step 5: Run** the tests, ruff and pyright.
- [ ] **Step 6: Commit** `feat(identity): add the password policy, argon2id hashing and the breach check`.

### Task 3: Permissions, sessions, tokens and lockout

**Files:**
- Create: `identity/permissions.py`, `identity/sessions.py`, `identity/tokens.py`, `identity/lockout.py`, `identity/settings.py`, `identity/roles.py`
- Modify: `backend/conftest.py` (`make_organization` calls `ensure_system_roles`)
- Tests: `backend/core/tests/test_permissions.py`; `tests/db/test_sessions.py`, `test_tokens.py`, `test_lockout.py`

**Interfaces (produces):**
- **`permissions.py`:**
  - `PERMISSIONS: tuple[str, ...]`: exactly the web app's list plus `"account.manage"`;
  - `SYSTEM_ROLES: dict[str, tuple[str, ...]]`, keyed by `super_admin`, `org_admin`, `recruiter`, `hiring_manager` and `interviewer`. Every role gets `account.manage`;
  - `permissions_for(role_keys: Iterable[str]) -> list[str]`, in catalogue order.
- `roles.py`: `ensure_system_roles(session, organization_id, platform: bool)`. It creates the missing system roles: `super_admin` only for the Platform organisation, and the other four everywhere else.
- **`IdentitySettings`** (`HV_` prefix):
  - `session_idle_minutes=30`, `session_absolute_hours=12`;
  - `hibp_enabled=True`;
  - `web_origin="https://app.hirevion.localhost"`;
  - `reset_token_minutes=30`, `verify_token_hours=24`, `set_password_token_hours=72`;
  - `lockout_threshold=5`, `lockout_base_seconds=60`, `lockout_max_seconds=3600`.
- `SessionContext` (frozen dataclass): `session_id`, `user_id`, `organization_id`, `csrf_hash`.
- `create_session(db, *, user_id, organization_id, ip, user_agent, settings, now) -> tuple[str, str, WebSession]` returns the session token, the CSRF token and the row. Both tokens are `secrets.token_urlsafe(32)`, and only their SHA-256 is stored.
- `resolve_session(db, token, *, settings, now) -> SessionContext | None`. It calls `auth_session` and returns None when any of these hold:
  - the session is revoked or expired;
  - it has been idle longer than allowed;
  - the user isn't `active`;
  - the organisation isn't `active`.

  Otherwise it updates `last_seen_at` in the tenant when the last update is more than 60 seconds old.
- `revoke_session(db, organization_id, user_id, session_id) -> bool` revokes one of the user's own sessions and returns False when it isn't theirs.
- `revoke_all_sessions(db, organization_id, user_id, *, except_session: UUID | None) -> int`.
- `list_sessions(db, organization_id, user_id) -> list[WebSession]` returns active sessions, newest first.
- `issue_token(session, *, organization_id, user_id, purpose, ttl, new_email=None, now) -> str` and `consume_token(db, token, purpose, *, now) -> AuthToken | None`.
  - Consuming is single-use (it sets `used_at`) and refuses expired tokens.
  - The lookup goes through a third `SECURITY DEFINER` function, `auth_token(p_token_hash bytea, p_purpose text)`, which returns (`token_id`, `organization_id`, `user_id`, `expires_at`, `used_at`, `new_email`), granted like the others. Add it in this task's migration `0007_auth_token_lookup.py`.
- **`Lockout(redis, settings)`:**
  - `retry_after(email) -> int | None`;
  - `record_failure(email) -> int | None`: after the threshold, the wait is `base * 2**(failures-threshold)`, capped at the maximum;
  - `reset(email)`;
  - keys are `lockout:{sha256(lower(email))}`, with a TTL of the maximum wait plus a day.

- [ ] **Step 1: Failing tests:**
  - **System roles:**
    - `make_organization`, which now calls `ensure_system_roles`, leaves the four organisation roles;
    - a second call adds nothing;
    - the Platform organisation keeps only `super_admin`.
  - **Permissions:**
    - `permissions_for(["recruiter","interviewer"])` is the ordered union;
    - every system role's permissions are in `PERMISSIONS`;
    - the catalogue matches `recruitment-platform/src/auth/permissions.ts`, parsed with a regex (a guard against drift until the client type check in Task 6).
  - **Sessions:**
    - create then resolve returns the context;
    - 31 idle minutes resolves to None, as does 12 hours and 1 second;
    - a revoked session, a disabled user or a suspended organisation resolves to None;
    - `last_seen_at` updates only after 60 seconds;
    - the stored hash isn't the token, and no column contains the token.
  - **Revocation:** `revoke_all_sessions` keeps the excepted session.
  - **Tokens:**
    - `consume_token` succeeds once, then returns None;
    - an expired token returns None;
    - a token with the wrong purpose returns None;
    - a token from organisation A resolves to A even when consumed with no tenant set.
  - **Lockout:**
    - 4 failures give None, and the 5th gives 60;
    - the 6th gives 120;
    - it caps at 3600;
    - `reset` clears it;
    - the key holds no plain email.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement**, and write migration `0007` for `auth_token()`.
- [ ] **Step 4: Run** `uv run pytest backend`, ruff and pyright.
- [ ] **Step 5: Commit** `feat(identity): add system roles, sessions, single-use tokens and progressive lockout`.

### Task 4: Email through the outbox

**Files:**
- Create: `hirevion_core/mail/settings.py`, `render.py`, `sender.py`, `consumer.py`, `runner.py`, and `templates/{en-IN,en-US}/{reset_password,password_changed,verify_email,email_change_requested}.{subject.txt,txt,html}.j2`
- Modify: `backend/core/pyproject.toml` (`uv add --package hirevion-core jinja2 aiosmtplib`), `.env.example` (`HV_SMTP_HOST=127.0.0.1`, `HV_SMTP_PORT=1025`, `HV_MAIL_FROM=Hirevion <no-reply@hirevion.localhost>`, `HV_API_RUN_WORKERS=true`), `.github/workflows/ci.yml` (`python` job: a Mailpit service on 1025/8025)
- Tests: `backend/core/tests/test_mail_render.py`, `tests/db/test_mail_delivery.py`

**Interfaces (produces):**
- `MAIL_TOPIC = "mail"`.
- `queue_mail(session, *, organization_id, template: MailTemplate, to: str, locale: str, context: dict[str, str]) -> None` writes an outbox event (topic `mail`, payload `{template, to, locale, context}`).
- `MailTemplate = Literal["reset_password","password_changed","verify_email","email_change_requested"]`.
- `render(template, locale, context) -> RenderedMail(subject, text, html)`.
  - Jinja2 with `autoescape=select_autoescape(["html"])` and `StrictUndefined`.
  - An unknown locale falls back to en-IN.
- `class MailSender(Protocol)`: `async def send(self, to: str, mail: RenderedMail) -> None`. `SmtpSender(settings)` implements it.
- `MailConsumer(redis, sender, group="mail", consumer=hostname)`:
  - `run_once() -> int`: `XREADGROUP`, render and send, then `XACK`;
  - a failed send is left pending and retried with `XAUTOCLAIM` after 60 seconds;
  - a message delivered 5 times goes to `stream:mail:dead`.
- `run_workers(core, stop: asyncio.Event)` runs `OutboxRelay(relay_db, redis).run_forever(stop)` and `MailConsumer.run_forever(stop)`.

- [ ] **Step 1: Failing tests:**
  - **Rendering:**
    - each template renders in both locales;
    - the HTML escapes `<script>` in a name;
    - a missing context key raises;
    - the reset link uses `HV_WEB_ORIGIN`.
  - **Delivery** (`db`, needs Mailpit):
    - `queue_mail` in a committed tenant transaction, then the relay's `run_once` and the consumer's `run_once`, leaves exactly one message in Mailpit (`GET http://127.0.0.1:8025/api/v1/messages`) with that subject and recipient;
    - a rolled-back transaction leaves no message;
    - a sender that raises leaves the stream entry pending, and a later `run_once` retries it;
    - the 5th failure moves it to the dead-letter stream.
  - Clean Mailpit before each test with `DELETE /api/v1/messages`.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement.** The templates use the locale's spelling; their subjects and bodies are the spec's four messages. Each email states who it's for and that the link expires.
- [ ] **Step 4: Run** the tests, ruff and pyright.
- [ ] **Step 5: Commit** `feat(mail): send templated email through the outbox`.

### Task 5: AuthService

**Files:**
- Create: `identity/service.py`
- Tests: `backend/core/tests/db/test_auth_service.py`

**Interfaces:**
- **Consumes:** Tasks 1–4.
- **Produces `AuthService(db, redis, policy, lockout, settings, audit: AuditService)`:**
  - `login(email, password, *, ip, user_agent, now) -> LoginOk | LoginRefused`:
    - `LoginOk(session_token, csrf_token, context)`;
    - `LoginRefused(retry_after: int | None)`.
  - `logout(ctx)`.
  - `change_password(ctx, current, new) -> list[PasswordProblem] | None`. A wrong current password returns `["wrong_current"]`; on success it ends the user's other sessions.
  - `request_reset(email, *, ip)`: returns nothing whether or not the account exists. It sends `reset_password` only to `active` users.
  - `reset_password(token, new) -> list[PasswordProblem] | None`: sets the hash and `password_changed_at`, marks the email verified, revokes every session, and sends `password_changed`.
  - `request_email_change(ctx, new_email, password) -> Literal["ok","wrong_password","unavailable"]`.
    - It issues a `verify_email` token (24 hours) and sends `verify_email` to the new address and `email_change_requested` to the old.
    - `unavailable` means the address is already in use. It answers the same as `ok` to the caller and sends nothing; the API returns 202 either way.
  - `verify_email(token) -> bool`: switches the email and sets `email_verified_at`.
  - `set_password(token, new) -> list[PasswordProblem] | None`: for invited users. It sets the password, activates the user and verifies the email.
  - `session_view(ctx) -> SessionView`, in ADR-0012's shape:
    - `user {id,name,email}`;
    - `organization {id,name}`, or null for the Platform organisation;
    - `roles: [role keys]`;
    - `permissions`.
- **Audit actions** (`AuditEntry.action`): `auth.login.succeeded`, `auth.login.failed`, `auth.logout`, `auth.lockout.started`, `auth.session.revoked`, `auth.password.changed`, `auth.password.reset_requested`, `auth.password.reset`, `auth.email.change_requested`, `auth.email.verified`.
  - The actor is the user.
  - Details hold the IP and user agent only, never the email typed at sign-in for unknown accounts.

- [ ] **Step 1: Failing tests:**
  - **Successful login** with the right password:
    - returns tokens, and the session resolves;
    - writes the `auth.login.succeeded` audit entry;
    - resets lockout;
    - rehashes a weaker stored hash.
  - **Failed login:** a wrong password gives `LoginRefused(None)` and writes `auth.login.failed`.
  - **Unknown emails** give `LoginRefused(None)`, write no audit entry, and still call `verify_password(None, …)`.
  - **Lockout:** the 5th failure gives `LoginRefused(60)` and writes `auth.lockout.started`. While locked, even the right password gives `LoginRefused(60)`, with the remaining wait.
  - **Who can't sign in:** disabled users, invited users (no password) and users of suspended organisations get `LoginRefused(None)`.
  - **Password change:**
    - the wrong current password is refused;
    - a 14-character password returns `["too_short"]`;
    - success ends the other sessions but keeps this one.
  - **Password reset:**
    - an unknown email sends nothing and returns normally;
    - a known email sends one `reset_password` email (checked through a fake `MailSender` or the outbox row);
    - after the reset, the old password fails, the new one works, every old session is gone, and a `password_changed` email is queued.
  - **Email change:**
    - the wrong password is refused;
    - an address already in use answers like success and sends nothing;
    - verifying switches the email;
    - the token works only once.
  - **Set password:** an invited user's token sets the password and activates the user; a second use fails.
  - **`session_view`:** the Platform super admin's shows `organization: null` and the super admin permissions; a recruiter's shows the recruiter permissions plus `account.manage`.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, ruff and pyright.
- [ ] **Step 5: Commit** `feat(identity): add the auth service`.

### Task 6: The auth API

**Files:**
- Create: `backend/api/src/hirevion_api/auth/{deps,csrf,schemas,router}.py`
- Modify: `app.py` (router, the `run_workers` background task when `HV_API_RUN_WORKERS`), `settings.py` (`allowed_origins="https://app.hirevion.localhost,http://localhost:3000,http://app.hirevion.localhost:3100"`, `run_workers=True`), `packages/api-client/openapi.json`, `schema.d.ts` (regenerated), `recruitment-platform/src/auth/permissions.ts` (adds `account.manage`, and checks against the client type)
- Tests: `backend/api/tests/test_auth_csrf.py`, `tests/test_auth_api.py` (`db`)

**Interfaces (produces):**
- **Dependencies:**
  - `current_session(request) -> SessionContext`, or 401 `unauthenticated`;
  - `optional_session(request) -> SessionContext | None`;
  - both read `__Host-hv_session`.
- **`CsrfMiddleware`:**
  - For `POST|PUT|PATCH|DELETE` with a session cookie: the `Origin` (or `Referer` origin) must be in `allowed_origins`, and `X-CSRF-Token` must equal `__Host-hv_csrf` and hash to the session's `csrf_hash`. Otherwise it answers 403 `csrf-failed`.
  - Without a session cookie, only the `Origin` is checked, for login, forgot, reset and verify.
- **Endpoints and responses:**

  | Endpoint | Response |
  |---|---|
  | `POST login` | 204, setting both cookies; 401 `invalid-credentials`; 429 `rate-limited` with `Retry-After` |
  | `POST logout` | 204, clearing both cookies |
  | `GET session` | 200 `SessionView`; 401 |
  | `GET sessions` | 200 `[{id, created_at, last_seen_at, ip, user_agent, current}]` |
  | `DELETE sessions/{id}` | 204; 404 |
  | `POST sessions/revoke-others` | 204 |
  | `POST password/change` | 204; 422 `password-rejected` with `errors[].detail` holding the codes; 401 `wrong-password` |
  | `POST password/forgot` | 202 |
  | `POST password/reset` | 204; 400 `invalid-token`; 422 `password-rejected` |
  | `POST password/set` | 204; 400; 422 |
  | `POST email/change` | 202; 401 `wrong-password` |
  | `POST email/verify` | 204; 400 `invalid-token` |

- **Cookies:**
  - `__Host-hv_session` (HttpOnly) and `__Host-hv_csrf` (readable), both `Secure; Path=/; SameSite=Lax`, with no `Max-Age`: browser-session cookies, since the server enforces expiry;
  - login rotates both.
- **Rate limits** (`hirevion_core.ratelimit`):
  - login: 10 a minute per IP, 5 a minute per email hash, 100 a minute per organisation;
  - forgot: 5 an hour per email hash, 20 an hour per IP;
  - all of them answer 429 with `Retry-After`.
- **`SessionView`** is a Pydantic model whose `permissions` is a list of a `Literal` of every permission. The OpenAPI document and the client therefore carry the catalogue, and `permissions.ts` asserts `Permission` equals the client's type (`Equal<>` type test), so drift fails typecheck.

- [ ] **Step 1: Failing tests:**
  - **CSRF** (unit, with a stub session lookup):
    - a POST with the cookie but no header gives 403;
    - a wrong header gives 403;
    - a foreign `Origin` gives 403;
    - a GET passes without the header;
    - login with a foreign `Origin` gives 403.
  - **The API** (`db`, ASGI client, base URL `http://app.hirevion.localhost`, `Origin` header set):
    - login sets both cookies with the right attributes;
    - the session endpoint then returns the contract;
    - logout clears both, after which the session endpoint gives 401;
    - a wrong password gives 401 with `invalid-credentials`, and an unknown email gives a byte-identical body;
    - 6 bad logins in a row: the 6th gives 429 with `Retry-After`;
    - forgot gives 202 for unknown and known emails alike (identical bodies);
    - reset with the token from the outbox payload gives 204, and the old cookie then gets 401;
    - the session list marks the current session, and deleting another session works;
    - password change with a short password gives 422 with `too_short`;
    - set-password works for an invited user;
    - the email change and verify flow works;
    - every response body is free of the password, the token and the hash (searched).
  - **OpenAPI:** `uv run hv openapi --check` fails until regenerated.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement**, then regenerate:
  ```sh
  uv run hv openapi
  pnpm --filter @hirevion/api-codegen generate
  ```
  Then add the type check to `permissions.ts`.
- [ ] **Step 4: Run** `uv run pytest backend`, ruff, pyright, `pnpm typecheck` and `pnpm test`.
- [ ] **Step 5: Commit** `feat(api): add sign-in, sessions, password and email endpoints`.

### Task 7: Developer commands

**Files:**
- Create: `tools/devcli/src/hirevion_devcli/identity.py`
- Modify: `cli.py`, `envfile.py` (`HV_SEED_PASSWORD`: 24 characters, generated), `.env.example`
- Tests: `tools/devcli/tests/test_identity.py` (`db`)

**Interfaces (produces):**
- `uv run hv create-super-admin --email E --name N` creates an invited Platform user with the `super_admin` role and prints `{HV_WEB_ORIGIN}/set-password/{token}` (72 hours). It refuses an email that already exists.
- `uv run hv seed-identity`:
  - creates the organisation "Acme Talent (dev)" (slug `acme-dev`) with its system roles, if it's missing;
  - creates one active user per organisation role, `{role}@acme.example.test`, with `HV_SEED_PASSWORD`;
  - creates a Platform super admin, `super@hirevion.example.test`;
  - is idempotent;
  - refuses to run when `HV_ENVIRONMENT=production`.
- `uv run hv worker` runs `run_workers` until Ctrl+C.

- [ ] **Step 1: Failing tests:**
  - **`create-super-admin`:**
    - prints a link whose token consumes as `set_password`;
    - a second run with the same email exits 1.
  - **`seed-identity`:**
    - running it twice leaves 5 users;
    - each can log in through `AuthService` with the seed password;
    - with `HV_ENVIRONMENT=production` it exits 1.
  - **`init-env`:** generates `HV_SEED_PASSWORD`.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests.
- [ ] **Step 5: Commit** `feat(devcli): add create-super-admin, seed-identity and worker`.

### Task 8: Web pages

**Files:**
- Create:
  - `src/auth/api.ts` (`signIn`, `signOut`, `forgotPassword`, `resetPassword`, `setPassword`, `verifyEmail`, all through `apiClient()`);
  - `src/auth/forms/*.tsx` (`LoginForm`, `ForgotPasswordForm`, `NewPasswordForm`);
  - `src/app/recruiter/(auth)/layout.tsx` (a centred card with the language menu);
  - `(auth)/login/page.tsx` (moved), `forgot-password/page.tsx`, `reset-password/[token]/page.tsx`, `set-password/[token]/page.tsx` and `verify-email/[token]/page.tsx`;
  - `src/app/recruiter/(shell)/account/page.tsx` with `src/account/{profile,password,email,sessions}.tsx`.
- Modify:
  - `src/auth/manifest.ts`: add `/account` with `account.manage`, section `account`, owner `SP-02a`;
  - `permissions.ts`: `account.manage` for every role;
  - `src/data/api.ts`: a CSRF middleware that reads `__Host-hv_csrf` and sets `X-CSRF-Token` on unsafe methods;
  - `src/shell/user-menu.tsx`: an "Account" link, and "Sign out" calls `signOut()`, then the server action that clears `hv_dev_role`;
  - `next.config.ts`: in development, `rewrites()` maps `/api/:path*` to `${HV_API_INTERNAL_URL}/api/:path*`;
  - both message catalogues.
- Tests:
  - `src/auth/forms/*.test.tsx`;
  - `src/data/api.test.ts` (CSRF middleware);
  - the manifest, tabs and route tests updated for `/account`;
  - the e2e route × role and pages suites cover `/account` automatically through the manifest.

**Behaviour:**
- **`LoginForm`:**
  - email and password fields (`autocomplete` `username` and `current-password`);
  - submit calls `signIn`;
  - 204 goes to `safeNext(next)` with a full navigation, so the proxy sees the new cookie;
  - 401 shows "Email or password is incorrect" in a `role="alert"` region, focused;
  - 429 shows "Too many attempts. Try again in N minutes";
  - the development role picker stays below a divider when the tools are on.
- **Forgot password** always shows "If an account exists for that email, we've sent a link", whatever the API says.
- **New password (reset and set):**
  - the password, plus a confirmation that must match;
  - client-side length hint;
  - API 422 codes become field errors in the user's language: `too_short`, `too_long`, `personal`, `common`, `breached`;
  - success goes to `/login?reset=1`, which shows a status message.
- **Verify email** posts on load, through a button, so link prefetchers can't use the token. It then shows success or "This link has expired".
- **Account page:**
  - **Profile:** name and language, saved through SP-02b's endpoint. In SP-02a only the language is stored, in the `hv_locale` cookie, and the name is shown read-only with the note "Your organisation admin can change your name".
  - **Password:** current, new and confirm.
  - **Email:** new email and password; then "Check your new inbox".
  - **Sessions:** a table with device, IP, last active, and "This device" or "Sign out"; plus "Sign out everywhere else".

- [ ] **Step 1: Failing tests** (Vitest + Testing Library, with `apiClient` mocked):
  - each form's labels;
  - `LoginForm`:
    - a 401 shows the alert;
    - a 429 shows the wait;
    - success navigates to the `next` target;
    - an unsafe `next` goes to `/dashboard`;
  - the new-password form maps each 422 code to its message, and a mismatched confirmation stays client-side;
  - the CSRF middleware adds the header only on unsafe methods;
  - the manifest test includes `/account`;
  - the catalogue-parity test passes with the new keys.
- [ ] **Step 2: Run** and watch them fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pnpm lint`, `pnpm typecheck`, `pnpm test`, and the existing e2e suite (`pnpm --filter @hirevion/recruitment-platform e2e`, still green without an API).
- [ ] **Step 5: Commit** `feat(web): add sign-in, password and account pages`.

### Task 9: End-to-end against the real API, CI and docs

**Files:**
- Modify: `recruitment-platform/playwright.config.ts`. `HV_E2E_API` chooses one of two modes, each its own invocation and build, so they never share `.next`:
  - **unset:** project `web`, the existing specs, with the current server (development sessions on);
  - **`HV_E2E_API=1`:** project `auth`, `e2e/auth/**`, against the real API, with a build that has `HV_WEB_DEV_TOOLS=false`, plus the gateway below.
- Create: `e2e/auth/{sign-in,password,account,csrf}.spec.ts` and `e2e/auth/mailpit.ts` (reads the latest message for an address)
- Modify: `.github/workflows/ci.yml` (`e2e-auth` job), `docs/runbooks/local-dev.md`
- Create: `docs/architecture/adr/0013-sign-in-and-sessions.md`; add it to the ADR index

**The `e2e-auth` job (ubuntu-24.04, 30 minutes):**
- **Services:** Postgres (pgvector image), Valkey and Mailpit, matching the `python` job.
- **Steps:**
  1. `uv sync --locked`, `uv run hv migrate`, `uv run hv seed-identity`.
  2. Start `uv run hv api --port 8000` in the background, with `HV_API_ALLOWED_ORIGINS=http://app.hirevion.localhost:3100` and `HV_HIBP_ENABLED=false`, and wait for `/api/v1/health/ready`.
  3. `pnpm install`, then install Chromium.
  4. `HV_E2E_API=1 pnpm --filter @hirevion/recruitment-platform exec playwright test --project auth`.
  5. Upload the report on failure.
- **Same-origin API:** the web server runs `next start` with `HV_API_INTERNAL_URL=http://127.0.0.1:8000`. A production rewrite isn't wanted, so Playwright's web server for this project runs a tiny Node proxy (`e2e/auth/gateway.mjs`): port 3100 sends `/api/*` to 8000 and everything else to `next start` on 3101.

**Specs:**
- **Sign-in:**
  - a recruiter signs in, sees the dashboard and their name in the account menu, signs out, and is sent to `/login` on revisiting `/jobs`;
  - a wrong password shows the alert;
  - 6 attempts show the wait message.
  - Session expiry is covered by Task 3's tests, and revocation by the account spec.
- **Password:**
  - forgot password, read the link from Mailpit, set a new password, sign in with it;
  - the old password fails;
  - a 14-character password shows "Use at least 15 characters".
- **Account:**
  - change email, follow the Mailpit link, and the menu shows the new email;
  - sign in from a second browser context, then "Sign out everywhere else" logs the second context out.
- **CSRF:** a `fetch('/api/v1/auth/sessions/revoke-others', {method:'POST'})` without the header is answered 403.

- [ ] **Step 1: Write the specs and the gateway.** Run them locally against `uv run hv up`, `uv run hv api`, `uv run hv seed-identity` and Mailpit.
- [ ] **Step 2: Add the CI job.** ADR-0013 records:
  - the decisions (server-side sessions, the `__Host-` cookies, double-submit CSRF, the lookup functions owned by `hirevion_auth`);
  - the breach check;
  - the lockout;
  - the email pipeline;
  - MFA in SP-19.

  The runbook gets "Sign in locally": `hv seed-identity`, the seed users and password, `hv create-super-admin`, Mailpit at `https://mail.hirevion.localhost`, and `hv worker`.
- [ ] **Step 3: Run the whole gate:**
  - `uv run pytest backend tools`, ruff and pyright;
  - `pnpm lint`, `typecheck` and `test`;
  - both Playwright projects.
- [ ] **Step 4: Commit** `test(web): add the sign-in end-to-end suite against the real API`, then `docs: add ADR-0013 sign-in and sessions`.
- [ ] **Step 5: Finish the branch:** push, all CI jobs green, fast-forward `main`, delete the branch.

## Self-review

- **Spec coverage:**
  - **Users, the Platform organisation, roles and the lookup:** Tasks 1 and 3.
  - **Passwords and the breach check:** Task 2.
  - **Sessions, lockout and tokens:** Task 3.
  - **Email and outbox delivery:** Task 4.
  - **Every flow, with its audit entries:** Task 5.
  - **The API:** Task 6.
    - endpoints, cookies, CSRF and rate limits;
    - the session contract;
    - the catalogue carried in the client type.
  - **The bootstrap and seed commands, and `hv worker`:** Task 7.
  - **The pages and the account menu:** Task 8.
  - **End-to-end, CI and docs:** Task 9.
- **Left for SP-02b:**
  - organisation and user administration, invitations, custom roles, the scoping and matrix tests, and step-up;
  - changing your own name: the account page shows it read-only until then.
