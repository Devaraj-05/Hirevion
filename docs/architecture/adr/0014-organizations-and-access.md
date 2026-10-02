# ADR-0014: Organisations and access: custom roles, guards, step-up, scope and the platform

- **Status:** Accepted
- **Date:** 2026-10-02
- **Sub-project:** SP-02b

## Context

- **PRD §6 and §9** ask for organisation administration: the profile, departments, teams, users, roles and permissions. **§81** asks for server-side authorisation and **§97** for an audited "Permissions changed".
- **Master plan §9** adds custom roles, resource scope, and step-up re-authentication for role changes. **§14's exit criterion** is an authorisation-matrix test over every endpoint and every role.
- **SP-02a (ADR-0013)** left the system roles and their permissions in code, and the session's permissions as a pure function of role keys.
- **The product owner's decision:** scoping is organisation-wide by default, with an optional limit to a user's teams.

## Decision

- **Permissions:**
  - **System roles** keep their permissions in code (`SYSTEM_ROLES`), so a release can extend them; they can't be edited.
  - **Custom roles** store theirs in `role_permissions`, and may hold anything but `platform.*`.
  - **Everyone holds `account.manage`.**
  - **Per request:** a request's permissions are read from the database (`load_grants`), so a change reaches people on their next request.
  - **Names:** role names are unique per organisation ignoring case, built-in names included.
  - **The session contract** gains `custom_roles` (names); `roles` stays the system keys.
- **Route guards:**
  - **`requires(*permissions, step_up=…)`:** the only way to guard a route. It refuses with 403 `forbidden` when the principal holds none of the permissions, then with 403 `step-up-required` when a sensitive change lacks a recent password confirmation.
  - **`UNGUARDED`** lists, with a reason, the public routes and those acting only on the signed-in user.
  - **The matrix test:**
    - fails for a route that is neither guarded nor in `UNGUARDED`;
    - pins every guard to a written-down table;
    - calls every guarded route as each of the five system roles.
- **Nobody acts beyond their own power:**
  - **Escalation:** nobody grants, by creating, editing, inviting with or assigning a role, a permission they don't hold.
  - **Outranked:** nobody changes the roles or status of a user, or edits a role, holding permissions they don't.
  - **Last admin:** an organisation keeps an active holder of its admin role (`org_admin`, or `super_admin` on the Platform).
  - **Self:** nobody disables themselves.
- **Step-up:**
  - **What needs it:** role changes, invitations, enabling or disabling users, custom-role changes and every platform organisation change. All need a password confirmed within `HV_STEP_UP_MINUTES` (10).
  - **How:** `POST /auth/step-up` marks the session.
  - **Lockout:** wrong passwords count towards the sign-in lockout.
  - **In the web app:** a dialog asks for the password and retries the call.
- **Invitations:**
  - **An invitation is a user in `invited` status** plus SP-02a's 72-hour set-password link, so there is no separate invitations table.
  - **Resend:** revokes the earlier links.
  - **Cancel:** deletes the invited user.
  - **An address in use anywhere** is refused as `email-taken`, without saying where.
- **Resource scope:**
  - `users.access_scope` is `organization` (the default) or `teams`.
  - `ResourceScope` and `scope_clause(team_column, owner_column)` keep a team-limited user to work owned by one of their current teams, or by them.
  - **Departments and teams are archived, never deleted;** an archived team stops widening anyone's scope.
- **The platform's organisations:**
  - **Listing:** super admins list every organisation through `platform_organizations()`, a `SECURITY DEFINER` function owned by `hirevion_auth`, like the sign-in lookups.
  - **Creating:** the application role may insert an organisation, but only inside that organisation's own tenant transaction (the tenant policy checks `id`).
  - **One transaction per action:** each platform action starts in the Platform tenant. It switches with `switch_tenant()` to the organisation it changes, records there, then switches back and records the same action in the platform chain. Both chains and the idempotency record commit together.
  - **Suspending** ends every session of the organisation's users and stops sign-in until reactivated.
- **Password hashing runs on a worker thread** (`hash_password_in_thread`, `verify_password_in_thread`). Each argon2id operation takes about 100 ms, and on the event loop it stalled every concurrent request.

## Consequences

- **SP-04 (jobs, candidates) and SP-07 (interviews)** filter their queries with `scope_clause`, and add assignment (a hiring manager's jobs, an interviewer's interviews) on top.
- **Every route a later sub-project adds** must be guarded or listed in `UNGUARDED`, and its guard written into the matrix's table; CI fails otherwise.
- **SP-19** adds MFA, which step-up can then ask for instead of the password.
- **SP-22's audit-log page** reads the `organization.*`, `department.*`, `team.*`, `user.*`, `role.*` and `platform.organization.*` actions recorded here.
- **The platform's organisation listing** reads all organisations through one function; at many thousands of organisations it will want an index-backed search (`pg_trgm`) behind the same function.
- **A sign-in-only custom role** (no `dashboard.view`) starts on the first page its permissions open; the web proxy redirects there from the dashboard.
- **`hv reset-limits`** clears local rate limits and lockouts; the sign-in suite runs it first and runs two browsers at a time, as CI does.
