# SP-07a Interviews and Invitations Implementation Plan

**Goal:** PRD §24, §25 and §80 (interviews pin a template version), plus the pieces SP-06 left to this part. The work:
- Interviews with the §35-independent lifecycle state machine (scheduled → invited → in progress ⇄ interrupted → completed → evaluating → evaluated; or expired, cancelled, abandoned), and an event history.
- Single and bulk assignment producing §24's nine fields and a pinned policy snapshot.
- Reviewers, invitations with all eight §25 contents (en-IN and en-US), reminders, expiry, rescheduling and cancellation.
- Candidate accounts created on invitation, with a set-password link to the candidate portal.
- The job's "Interview Template" field (PRD §11), the organisation's support email, application stages `interview` and `interviewed`, and the `interviews.manage` permission.

**Architecture:**
- **`hirevion_core.interviews.lifecycle`:** statuses, the transition table, `transition()` (event row, audit entry, outbox event).
- **`hirevion_core.interviews.assignment`:** assigning (single and bulk), rescheduling, cancelling, reviewers, listing within the resource scope.
- **`hirevion_core.interviews.invitations`:** the §25 contents, the four emails, invitation records.
- **`hirevion_core.candidate_access.accounts`:** candidate accounts and their single-use links (set password, reset).
- **`hirevion_core.interviews.scheduler`:** the worker's loop: reminders and expiry, across organisations through one SECURITY DEFINER function.
- **The API:** `/interviews` (list, create, bulk, detail, invitation, reschedule, cancel, reviewers) and `/dashboard` (the interview KPIs; H0.2 adds the rest).
- **The web app:** `/interviews` (Upcoming, Live, Completed), `/interviews/[id]`, "Create interview" on the ranking, the candidates' Interview and Completed tabs, the dashboard's interview figures.

## Decisions (defaults; the product owner asked to build without stopping)

- **The nine §24 fields:** interview id (also shown as `IV-0042`), candidate, job, template version (`template_id` + `template_version`), start window (`starts_at`), expiry (`expires_at`), duration (the template version's), status, proctoring policy (a JSON snapshot).
- **The policy snapshot** is copied from the template version at assignment and never changes: proctoring level and the checks it turns on, third eye, recording, coding, the system checks that are mandatory, the resume policy (5-minute grace, at most 3 interruptions, the timer pauses while interrupted), the answer mode (`voice`) and `policy_version` 1 (SP-14 versions editable policies). The template version's pinned questions are copied too. So editing the template afterwards changes nothing for the interview (exit criterion).
- **Statuses and transitions** (`lifecycle.TRANSITIONS`):
  - `scheduled` → `invited` (invitation sent), `cancelled`, `expired`;
  - `invited` → `in_progress` (SP-09), `cancelled`, `expired`, `invited` (rescheduled);
  - `in_progress` ⇄ `interrupted`; both → `completed` or `abandoned`;
  - `completed` → `evaluating` → `evaluated` (SP-10);
  - `expired` → `invited` (rescheduled with a new window).
  - Every change writes an `interview_events` row and an audit entry; the creating, starting and completing ones also queue `interview.created`, `interview.started` and `interview.completed` for SP-18's webhooks.
- **Assignment rules:**
  - The application must be in the reader's scope, its job open, and its stage not `uploaded` or `rejected`.
  - At most one active interview (scheduled, invited, in progress or interrupted) per application, enforced by a partial unique index.
  - The template must be active; the version defaults to its current one, or to the job's interview template.
  - The window: start before end, end in the future, at least the duration long, at most 30 days.
  - The candidate needs an email address, or the invitation can't go.
  - **Bulk:** up to 200 applications at once; each one that breaks a rule is skipped with its code (`no-email`, `already-assigned`, `stage`, ...), and the rest are created. The answer lists both.
- **Scope:** the interview copies the job's team and recruiter, so the resource scope (ADR-0014) applies as it does to jobs. Someone without `candidates.view` (the interviewer role) sees only the interviews they review.
- **Candidate accounts:** one per candidate per organisation, created at the first invitation, `invited` until the candidate sets a password from the emailed link (a `candidate_tokens` row, valid 7 days). An active account gets a sign-in link instead. Accounts are found by email before the tenant is known through `auth_candidate_by_email`, as recruiter sign-in does (ADR-0013). Candidate passwords need 12 characters: the device key and the new-device code (SP-07c) are a second factor.
- **Invitations (§25):** company, job, duration, window (in the interview's time zone, formatted for en-IN or en-US), desktop instructions (the portal's download page), system requirements, the privacy and recording notice (what this interview records, and the portal's notices page), and support (the organisation's support email, else the platform's). Each sent email is an `invitations` row (kind `invitation`, `reminder`, `reschedule` or `cancellation`) with those contents, so the portal and audits can show what was sent.
- **Reminders and expiry:** the worker's scheduler runs every 60 s. It reminds 24 hours before the window opens (if the invitation went out earlier than that) and 24 hours before an unstarted window closes, once each, and expires invited or scheduled interviews whose window has closed. A cross-organisation SECURITY DEFINER function, owned by a new `hirevion_scheduler` role that can't log in, lists what's due; each one is then handled in its tenant's transaction with a row lock, so two workers never send twice. SP-18 takes this loop over.
- **Rescheduling** replaces the window, counts `reschedule_count`, clears the reminders, re-sends the invitation (kind `reschedule`) and moves an expired interview back to `invited`. **Cancelling** needs a reason and emails the candidate.
- **Application stages:** inviting moves the application to `interview`; completion (SP-09) moves it to `interviewed`. The candidates' Interview and Completed tabs list those.
- **Permissions:** new `interviews.manage` (org admins and recruiters). Viewing stays `interviews.view`.
- **Audit:** `interview.created`, `interview.invited`, `interview.rescheduled`, `interview.cancelled`, `interview.expired`, `interview.reviewers.changed`, plus every status change through `interview.status_changed`.

## Tasks

1. **Schema (migration 0013):** `interviews`, `interview_events`, `interview_reviewers`, `invitations`, `candidate_accounts`, `candidate_tokens`; `organizations.support_email`; `jobs.interview_template_id`; the application stages; the lookup and scheduler functions and role. Isolation and models-match tests.
2. **Lifecycle:** the transition table and `transition()`, with tests for every allowed and refused move.
3. **Assignment:** single and bulk, the rules, the policy snapshot, scope, reviewers, reschedule and cancel. Tests, including "editing the template leaves the interview pinned" and bulk skips.
4. **Invitations and accounts:** the contents, the four templates in both languages, candidate accounts and links. A Mailpit test that reads all eight contents back.
5. **Scheduler:** due interviews across organisations, reminders and expiry, idempotent under two workers. Tests.
6. **API:** the routes, the permission, the authorisation matrix, the job's template field, the support email, `/dashboard`. OpenAPI and codegen.
7. **Web:** the interviews list and detail, the create dialog on the ranking, the candidates' tabs, the dashboard figures, the job form's template field and the organisation's support email. Component tests.
8. **Playwright** (create a job, shortlist, create an interview, the invitation in Mailpit), ADR-0020, runbook, threat model, Appendix A (§24, §25, §80), PENDING_TASKS.md.
