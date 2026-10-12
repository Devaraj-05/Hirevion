# SP-07b Candidate Portal Plan

**Goal:** master plan §6.3 on the `candidate.` host: the invitation's set-password link, sign-in, reset and sign-out; the candidate's interviews with their windows; the app download; §83's ten disclosures and six policies; a report placeholder (§99, filled by SP-17); and candidate requests that recruiters act on. ADR-0022.

## Decisions

- **Sessions:** `candidate_web_sessions`, ADR-0013's mechanics (opaque 256-bit token, SHA-256 stored, 30 min idle, 12 h absolute, new session at sign-in), in their own cookies `__Host-hv_candidate_session` and `__Host-hv_candidate_csrf`. Found by `auth_candidate_session` (SECURITY DEFINER, owned by `hirevion_auth`).
- **CSRF:** the middleware picks the cookie pair by path: `/api/v1/portal/*` uses the candidate pair and `HV_API_PORTAL_ORIGINS`; everything else the recruiter pair and `HV_API_ALLOWED_ORIGINS`. Neither cookie works on the other's routes.
- **Gateway:** Caddy's candidate host sends only `/api/v1/portal/*` to the API (the e2e gateway does the same).
- **Passwords:** 12 characters (ADR-0020). The lockout key is the desktop's (`candidate:<email>`), so both doors share one budget. A set-password link also verifies the email. Reset revokes the candidate's web sessions and desktop refresh families. A forgot request for an account still `invited` sends a fresh set-password link.
- **Several organisations:** sign-in picks the matching account with the soonest interview still to take, else the newest.
- **Notices:** `GET /portal/notices` (public) serves `docs/policies/` (`HV_POLICIES_DIR`) and §83's ten disclosures; the web renders the Markdown with a small safe renderer (no HTML).
- **Download:** `GET /portal/downloads` (public): the stable channel's download page, the newest full-rollout release per architecture, and the system requirements invitations list.
- **Requests:** `candidate_requests`, ten kinds: reschedule, support, accommodation, alternative process, data access, correction, erasure, grievance, nomination, consent withdrawal. Statuses open → in progress → resolved or declined. Reschedule and accommodation name one of the candidate's interviews and add an interview event; an accommodation before the interview also opens SP-09's accommodation request. Each request is audited and acknowledged by email.
- **Recruiters:** `candidates.requests.view` (org admin, recruiter, hiring manager) and `candidates.requests.manage` (org admin, recruiter); `/candidates/requests` lists them within the resource scope and records status changes with a reply the candidate sees.

## Tasks

1. Migration 0019 and models; schema, isolation and models-match tests.
2. Core: `hirevion_core.candidate_portal` (sessions, auth service, interviews, requests, notices). DB tests first.
3. API: `/portal/auth/*`, `/portal/interviews|requests|notices|downloads`, `/candidate-requests`; CSRF by path; settings, matrix, OpenAPI, codegen. API tests first.
4. Web: portal pages (login, forgot, reset, invitation, interviews with countdowns, download, notices, report, requests), the recruiter requests page, en-IN and en-US. Vitest first.
5. Caddy, gateway, Playwright `e2e/auth/portal.spec.ts`: Mailpit invitation → set password → interview listed → reschedule request seen by the recruiter.
6. ADR-0022, runbook, threat model, Appendix A (§25, §83, §99), PENDING_TASKS.md, STATUS.md.

## Tests

`test_candidate_portal_schema.py`, `test_candidate_portal.py` (core), `test_portal_api.py`, `test_auth_csrf.py` (portal cases), the authorisation matrix, `test_mail_render.py`; web `portal/*.test.tsx`, `markdown.test.tsx`, `candidate-requests` test; Playwright `portal.spec.ts`.
