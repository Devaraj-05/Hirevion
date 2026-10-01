# SP-02 Identity and access: design

- **Date:** 2026-10-01
- **Status:** Approved by the product owner on 2026-10-01 (one organisation per account, HIBP plus a local list, organisation-wide scoping with an optional team limit, MFA moved to SP-19, the SP-02a/SP-02b split)
- **Master plan:** §14 SP-02, §9 (web sessions, passwords, authorisation, audit), D7, PRD §6, §8, §9, §81, §82, §97

## Goal

Real sign-in for the Recruitment Platform, and the organisation, user and role management behind it, so every later sub-project can rely on a server-checked session and a permission matrix. SP-03's web app already calls the session contract (ADR-0012); SP-02 serves it.

## Delivery: two parts

- **SP-02a, accounts and sign-in:**
  - users, password sign-in and sign-out, and server-side sessions;
  - password reset and email verification;
  - the breached-password check, lockout and rate limits;
  - the session list ("sign out other devices") and `GET /api/v1/auth/session`;
  - the five system roles, held server-side;
  - auditing of sign-in and sign-out;
  - the sign-in, password and account pages.
- **SP-02b, organisations and access:**
  - super-admin create and suspend for organisations; the organisation profile, departments, teams and users;
  - email invitations;
  - custom roles and the permission matrix UI;
  - resource scoping;
  - step-up re-authentication for role changes;
  - auditing of permission changes;
  - the admin and platform pages (Users, Roles, Teams, Departments, Organisation, Platform organisations).
  - Its plan is written after SP-02a merges.
- **Moved to SP-19:** TOTP MFA with recovery codes (master plan §14 and Appendix A updated). Until then the password minimum is 15 characters, NIST SP 800-63B-4's rule for single-factor passwords (master plan §9).

## Decisions

### Accounts and organisations

- **One organisation per account.** An email is unique across the platform (case-insensitive), and a user belongs to exactly one organisation. An agency recruiter who serves two employers uses two emails.
- **The Platform organisation.** A reserved organisation (slug `platform`, id `00000000-0000-7000-8000-000000000001`, created by migration) holds the super admins.
  - Its audit chain is the platform audit log.
  - The session contract reports `organization: null` for its users, as ADR-0012 expects.
  - It can't be suspended, renamed or given other members.
- **Users:**
  - **Fields:** `id`, `organization_id`, `email` (citext), `name`, `locale` (en-IN default), `status`, `password_hash` (argon2id; null until set), `email_verified_at`, `password_changed_at`, and timestamps.
  - **Statuses:**
    - `invited`: created, no password yet;
    - `active`;
    - `disabled`: by an admin; can't sign in, and every session ends.
  - **Signing in also needs** an active organisation; a suspended organisation can't sign in.
- **Roles (SP-02a builds the tables; SP-02b adds editing):**
  - `roles`: per organisation; the system roles are created with each organisation and can't be edited.
  - `role_permissions`.
  - `user_roles`.
  - **The permission catalogue and the five system roles** (super admin, organisation admin, recruiter, hiring manager, interviewer) live in code, moved from the web app's provisional map. A migration seeds them.
  - **A session's permissions** are the union of its roles' permissions.

### Row-level security and the sign-in lookup

- **Tenant scoping.** Every new table carries `organization_id` with the forced tenant policy from ADR-0009, and joins the tenant-isolation suite.
- **The sign-in lookup.** Sign-in has to find a user before the organisation is known, and every API call has to find its session. Two `SECURITY DEFINER` functions do this:
  - `auth_user_by_email(email)` returns the user's id, organisation, status, password hash and organisation status;
  - `auth_session(token_hash)` returns the session, its user and its organisation.
- **Their owner** is a `NOLOGIN` role, `hirevion_auth`, which has a read-only all-rows policy on `users`, `organizations` and `web_sessions` and nothing else. `hirevion_app` may only execute the two functions. No role bypasses row-level security, so this works on managed Postgres without superuser rights.
- **After the lookup,** the request runs in `db.tenant(organization_id)` as usual.

### Passwords

- **Hashing:** argon2id with the library's current recommended parameters. The hash is rehashed at sign-in when the parameters change.
- **Policy:**
  - 15–128 characters, any characters (Unicode NFKC-normalised), no composition rules;
  - not the email address, the user's name or the organisation's name;
  - not breached or common.
- **Breach check:**
  - A bundled list of the 100,000 most common passwords (SecLists, MIT licence) always applies.
  - The Have I Been Pwned range API is checked when reachable:
    - only the first 5 hex characters of the SHA-1 hash are sent, with `Add-Padding: true`;
    - a 2-second timeout;
    - if HIBP is unreachable, only the local list applies, and a warning is logged.
  - Passwords and hashes are never logged.
  - Tests and CI use a fake HIBP.

### Sign-in, sessions and CSRF

- **Login:** `POST /api/v1/auth/login {email, password}`.
  - **Rate limits** (GCRA, ADR-0010): per IP, per email and per organisation.
  - **Progressive lockout** in Valkey: after 5 failures an account waits 1 minute, doubling to 1 hour. A success resets it.
  - **Unknown emails** run a dummy argon2id verify and get the same answer and timing: "Email or password is incorrect".
  - **A locked account** gets the same answer plus a `Retry-After`, without saying whether the password was right.
- **Sessions:**
  - **Storage:** an opaque 256-bit token, of which `web_sessions` keeps only the SHA-256, alongside user, organisation, created and last-seen times, absolute expiry, IP, user agent and revoked time.
  - **Lifetime:** 30 minutes idle and 12 hours absolute. `last_seen_at` is written at most once a minute.
  - **Rotation:** a new session at every sign-in; reset and admin disable revoke all of them.
- **Cookies:**
  - `__Host-hv_session`: Secure, HttpOnly, SameSite=Lax, Path=/.
  - `__Host-hv_csrf`: readable by scripts.
- **CSRF:** every state-changing request made with the session cookie must send the CSRF value in `X-CSRF-Token` and come from an allowed `Origin` (`HV_API_ALLOWED_ORIGINS`). Login checks the `Origin` only.
- **Endpoints** (all under `/api/v1/auth`):
  - `POST login`, `POST logout`;
  - `GET session` (ADR-0012's contract: `{user, organization, roles, permissions}`, or 401);
  - `GET sessions`, `DELETE sessions/{id}`, `POST sessions/revoke-others`;
  - `POST password/change` (needs the current password; ends the user's other sessions);
  - `POST password/forgot`, `POST password/reset`;
  - `POST email/change`, `POST email/verify`.
- **Password reset:**
  - `forgot` always answers 202 with the same body, so it never reveals whether an account exists.
  - The email carries a single-use, 30-minute token, stored hashed.
  - `reset` sets the password, marks the email verified, ends every session and sends a "your password changed" email.
- **Email verification:**
  - A user changes their email from the account page.
  - The new address gets a single-use, 24-hour link; the old address is told.
  - The email changes only when the link is used.
  - The set-password link (from bootstrap, and SP-02b's invitations) also verifies the address.
- **The first super admin:** `uv run hv create-super-admin --email … --name …` creates an invited Platform user and prints a one-time set-password link. No password goes on a command line.

### Email

- **Sending:** `hirevion_core.mail`: SMTP (aiosmtplib), Mailpit locally.
- **Templates:**
  - Jinja2 with autoescape, a text and an HTML part for each message, per locale (en-IN, en-US).
  - SP-02a sends four: reset password, password changed, verify email, email change requested.
  - SP-18 later generalises them.
- **Delivery:** a message is written to the outbox (ADR-0009) in the same transaction as the change that causes it, so nothing is sent for a change that rolls back.
  - The outbox relay (built in SP-01, not yet running anywhere) publishes it to the `mail` stream.
  - A mail consumer (consumer group `mail`) renders and sends it, then acknowledges it. Delivery is at least once: a crash between sending and acknowledging can repeat an email.
- **Where they run:**
  - The relay and the mail consumer run as background tasks in the API process (`HV_API_RUN_WORKERS`, on by default).
  - `uv run hv worker` runs them alone, for a separate container.
  - SP-18's worker takes them over later.

### Audit (PRD §97)

- **Recorded** in the user's organisation chain:
  - sign-in success and failure (known accounts only);
  - sign-out;
  - session revoked;
  - password changed, reset requested and reset completed;
  - email change requested and verified;
  - lockout started.
- **Unknown-email failures** go to the rate limiter and the redacted application log, not the audit chain.

### Web app

- **Pages on the recruiter host:**
  - `/login`: email and password. The development role picker stays below it when the development tools are on.
  - `/forgot-password`, `/reset-password/[token]` and `/verify-email/[token]`.
  - `/account`: profile (name, language), password, email, and the session list with "sign out" per session and "sign out everywhere else".
- **The account page joins the shell** as a manifest route every role may open (`account.manage`).
- **The account menu's sign-out** calls the API, then clears the development role.
- **`next dev`** rewrites `/api/*` to `HV_API_INTERNAL_URL`, so sign-in works without Caddy. Production relies on the gateway.
- **The API client** sends the CSRF header on unsafe methods.
- **Development sessions** stay as they are: the route × role suite keeps running without an API.
  - `uv run hv seed-identity` creates a demo organisation with one real user per role.
  - Their password is `HV_SEED_PASSWORD`, which `hv init-env` generates.
  - Their emails are on `example.test`.

### Settings

- `HV_API_ALLOWED_ORIGINS`
- `HV_SESSION_IDLE_MINUTES` (30) and `HV_SESSION_ABSOLUTE_HOURS` (12)
- `HV_HIBP_ENABLED` (true; false in CI)
- `HV_SMTP_HOST` and `HV_SMTP_PORT` (Mailpit)
- `HV_MAIL_FROM`
- `HV_WEB_ORIGIN` (for the links in emails)
- `HV_API_RUN_WORKERS` (true)

## Testing

- **Unit:**
  - password policy and the breach check (HIBP faked, unreachable and padded);
  - lockout timing;
  - token hashing;
  - CSRF and Origin rules;
  - email rendering in both locales.
- **Database (`pytest -m db`):**
  - the lookup functions, and that they expose nothing else;
  - an email is sent only for a committed change, and reaches Mailpit through the relay and the consumer;
  - session expiry and revocation;
  - the tenant-isolation suite over every new table;
  - the Platform organisation;
  - the audit entries for each action.
- **API:**
  - each endpoint's success and failure, including enumeration-safe answers, rate limits and lockout;
  - the session contract matches what the web app parses.
- **Playwright, against the real API** (a new CI job with Postgres, Valkey and Mailpit):
  - sign in and out;
  - a wrong password, then lockout;
  - forgot password, read the email from Mailpit, reset, sign in;
  - change email and verify;
  - sign out another session;
  - an expired session goes to sign-in;
  - a CSRF-less request is refused.
- **SP-02b adds** the authorisation-matrix test (every endpoint × every role).

## Out of scope

- **Later sub-projects:**
  - MFA, passkeys and SSO (SP-19);
  - candidate accounts and device-bound tokens (SP-07);
  - notification preferences and general templates (SP-18).
- **SP-02b:** organisation and user administration, invitations, custom roles and scoping.
