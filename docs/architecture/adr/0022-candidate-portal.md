# ADR-0022: The candidate portal: its own cookies and origins, the invitation's link, §83's notices and candidate requests

- **Status:** Accepted
- **Date:** 2026-10-12
- **Sub-project:** SP-07b

## Context

- **Master plan §6.3** puts the candidate portal on its own host (`candidate.`) with isolated cookies: accept the invitation and set a password, the app download, the notices, the interview's status and window, the candidate-visible report (PRD §99) and five kinds of request.
- **The invitation (PRD §25, ADR-0020)** already links to `/invitation/<token>`, `/download`, `/notices`, `/requests` and `/forgot-password` on that host, and creates `invited` candidate accounts with single-use links.
- **PRD §83** asks for ten disclosures and six policies before an interview; D1 wrote the policies as drafts in `docs/policies/`.
- **One Next.js app serves both hosts** (ADR-0012) and **one API serves both**, so the recruiter's session must never work for a candidate or the reverse, even under `next dev` where both are `localhost`.
- The product owner asked to build without pausing; these defaults can be revisited.

## Decision

- **Sessions:** ADR-0013's server-side sessions for candidate accounts (`candidate_web_sessions`): an opaque 256-bit token stored as SHA-256, 30 minutes idle, 12 hours absolute, a new session at every sign-in. Found before the tenant is known by `auth_candidate_session`, a SECURITY DEFINER function owned by `hirevion_auth`.
- **Cookies:** `__Host-hv_candidate_session` and `__Host-hv_candidate_csrf`, named apart from the recruiter's `__Host-hv_session` and `__Host-hv_csrf`. Only `/api/v1/portal/*` reads them; no portal route reads the recruiter's.
- **CSRF by path:** the middleware takes the candidate's cookie pair and `HV_API_PORTAL_ORIGINS` for `/api/v1/portal/*`, the recruiter's pair and `HV_API_ALLOWED_ORIGINS` for everything else; portal sign-in routes need a portal Origin even without a cookie. A recruiter cookie sent from the portal's origin, or a recruiter CSRF token on a portal route, is refused.
- **Gateway:** Caddy's `candidate.` host proxies only `/api/v1/portal/*` to the API (other `/api/*` is 404) and everything else to the web app; the end-to-end gateway does the same.
- **Sign-in and passwords:** the recruiter side's rules for candidates: identical refusals for unknown emails after the same argon2id work, `password/forgot` always 202, rate limits per IP and email that fail closed (counted apart from the recruiter's), and the desktop's lockout key (`candidate:<email>`, ADR-0021) so the portal and the app share one failure budget. Passwords need 12 characters (ADR-0020). The invitation's link sets the first password, activates the account and confirms the email address (only its owner could follow it). A forgotten-password request sends a reset link to an active account and a fresh invitation link to one still `invited`. A reset ends every portal session and every desktop refresh family of the account.
- **Several organisations:** sign-in picks the matching account with the soonest interview still to take (ADR-0021's rule), else the newest.
- **Pages fetch on the server:** portal pages read the API from the server with only the candidate's cookie, so a recruiter cookie never travels with them and a failing API shows "not available" rather than an error. Forms post from the browser with the candidate's CSRF token.
- **Interviews:** every interview the candidate was sent (not `scheduled`), soonest first, with its window in its own time zone, a countdown driven by the server's clock, whether it can be taken now, and what it records.
- **Notices:** `GET /portal/notices` (public, as the invitation links to it before a password exists) serves §83's ten disclosures (the interview notice's purposes, `CONSENT_PURPOSES`) and the six policies from `docs/policies/` (`HV_POLICIES_DIR`). The web renders their Markdown with a small renderer that builds React elements, never HTML; links to another policy jump within the page, and any scheme but http(s) and mailto is shown as text.
- **Download:** `GET /portal/downloads` (public) gives SP-07c's stable channel's download page and minimum version, the newest fully rolled-out release per architecture, and the invitation's system requirements.
- **Report:** a page stating §99's five items the organisation may share; SP-17 fills it.
- **Requests (`candidate_requests`):** ten kinds (reschedule, support, accommodation, alternative process, data access, correction, erasure, grievance, nomination, consent withdrawal), each with the details its kind needs and nothing else. Reschedule and accommodation name one of the candidate's own interviews; a reschedule of an interview that has run is refused. Each request is audited (`candidate.request.created`), acknowledged by email (`candidate_request_received`, with an `RQ-` reference) and, when it names an interview, recorded in its history (`reschedule.requested` and so on). An accommodation asked for before the interview starts also opens SP-09's accommodation request, which the recruiter decides on the interview's page. Creation is idempotent (`Idempotency-Key`) and limited to 20 an hour per account.
- **Recruiters:** `candidates.requests.view` (org admins, recruiters, hiring managers) and `candidates.requests.manage` (org admins, recruiters). `/candidates/requests` lists requests of the candidates the reader's resource scope reaches (ADR-0014) and moves each from open to in progress, resolved or declined, with a reply the candidate reads in the portal; a closed request stays closed. Changes are audited (`candidate.request.updated`).

## Consequences

- **A leaked recruiter cookie is useless on the portal and the reverse**, and the portal's host can't reach the recruiter API at all through the gateway.
- **The policies are served from the repository's drafts** until SP-22 lets each organisation publish its own; a deployment must ship `docs/policies/` or set `HV_POLICIES_DIR`. They stay marked as drafts for legal review.
- **Acting on data-rights requests is manual:** the request, its acknowledgement, the reply and the audit trail are recorded, but erasure, export and consent changes themselves are SP-22's retention and deletion tooling. Status changes notify the candidate through the portal only; email notifications for them come with SP-18.
- **The report page is a placeholder** until SP-17 adds the candidate-visible report and its per-organisation configuration.
- **Each portal page costs one session lookup** in the layout and one in the page; cache it if traces show it.
