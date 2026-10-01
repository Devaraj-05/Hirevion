# ADR-0013: Sign-in and sessions: server-side sessions, the lookup role, CSRF and email

- **Status:** Accepted
- **Date:** 2026-10-01
- **Sub-project:** SP-02a

## Context

- **PRD §8** asks for email and password sign-in, session management, password reset and rate limiting on the Recruitment Platform. PRD §82 asks for session expiry and audit logs. Master plan §9 fixes the mechanics.
- **Row-level security is forced on every tenant table** (ADR-0009), and the application role can't bypass it. Sign-in, though, has to find a user by email before it knows the organisation, and every request has to find its session the same way.
- **The web app already calls `GET /api/v1/auth/session`** in ADR-0012's shape.
- **MFA moved to SP-19** (product owner, 2026-10-01). Until then a password is the only factor.

## Decision

- **Accounts.**
  - One organisation per account; the email is unique across the platform (case-insensitive).
  - Super admins belong to a reserved **Platform** organisation. Its audit chain is the platform log, and the session contract reports it as `organization: null`.
- **The lookup role.**
  - `hirevion_auth` can't log in and doesn't bypass row-level security.
  - It holds read-only, all-rows policies on `users`, `organizations`, `web_sessions` and `auth_tokens`.
  - It owns three `SECURITY DEFINER` functions: `auth_user_by_email`, `auth_session` and `auth_token`. The application role may only execute them.
  - Everything after the lookup runs in the tenant's transaction.
  - This needs no superuser or BYPASSRLS, so it works on managed Postgres. The isolation harness audits the role.
- **Passwords.**
  - argon2id (the library's current parameters; weaker hashes are upgraded at sign-in).
  - 15–128 characters after NFKC, with no composition rules.
  - Not the user's email, name or organisation name.
  - **Not breached:** a bundled SecLists list (MIT) always applies, and Have I Been Pwned's range API (5-character SHA-1 prefix, padded, 2-second timeout) when it answers.
- **Sessions.**
  - An opaque 256-bit token in `__Host-hv_session` (HttpOnly, Secure, SameSite=Lax, Path=/); the database stores only its SHA-256.
  - 30 minutes idle and 12 hours absolute; `last_seen_at` is written at most once a minute.
  - A new session at every sign-in. A password reset, a password change (other sessions) and "sign out everywhere else" revoke sessions.
- **CSRF.** Double submit: `__Host-hv_csrf` is readable, and the app repeats it in `X-CSRF-Token`.
  - **With the session cookie,** a state-changing request also needs an allowed `Origin` (or a same-origin `Referer`), and its CSRF cookie must belong to the session.
  - **Sign-in routes** need the `Origin` without a cookie too.
  - **Bearer-token clients** (the desktop app, the public API) send no cookie and are unaffected.
- **Nothing reveals whether an account exists.**
  - An unknown email gets the same 401 (byte for byte), after the same argon2id work, as a wrong password, and shares its lockout.
  - `password/forgot` always answers 202.
  - A locked account isn't told whether its password was right.
- **Lockout and limits.**
  - After 5 failures an email waits 1 minute, doubling to 1 hour. Keys hold only an email hash.
  - Per-IP and per-email rate limits on sign-in, forgot and token routes fail closed when Valkey is down.
- **Single-use links.**
  - Reset (30 minutes), first password (72 hours) and email confirmation (24 hours) tokens are stored hashed.
  - A link is found without a tenant, then claimed inside the transaction that acts on it, so a rejected password leaves it usable and two uses can't both succeed.
  - The email confirmation page waits for a click, so mail scanners can't use the token.
- **Email.**
  - A change queues its email in the outbox in the same transaction; nothing goes out for a rollback.
  - The relay publishes it, and a consumer renders (Jinja2, text and HTML, en-IN and en-US), sends (SMTP; Mailpit locally) and acknowledges it.
  - A failed send is retried after a minute and dead-lettered after 5 attempts. Repeats are de-duplicated by event id, and sent entries are deleted.
  - Both run inside the API (`HV_API_RUN_WORKERS`) or as `hv worker`.
- **Audit.** Every action on a known account goes into its organisation's chain: sign-in success and failure, lockout, sign-out, session revoked, password changed, reset requested and completed, account activated, email change requested and verified.
- **Bootstrap.**
  - `hv create-super-admin` prints a set-password link; no password ever goes on a command line.
  - `hv seed-identity` creates a development organisation with a user per role, and refuses production.

## Consequences

- **SP-02b** builds organisation and user administration, invitations (reusing the set-password link), custom roles and step-up on this base.
- **SP-19** adds MFA; the 15-character minimum can then drop to 8 for MFA users.
- **Per-organisation sign-in limits** (master plan §9) need SP-02b's organisation settings; today the limits are per IP and per email.
- **Reset and confirmation links sit in `outbox_events` payloads** until SP-22's retention purges published mail events. They are single-use and short-lived, but retention must treat them as secrets.
- **Every guarded page costs a session lookup** in the proxy and another in the page. The lookup is one indexed query; cache it if it ever shows up in traces.
- **`next dev` proxies `/api/*`** so sign-in works without Caddy. Production builds rely on the gateway.
