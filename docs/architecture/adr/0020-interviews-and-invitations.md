# ADR-0020: Interviews and invitations: pinned policy, a lifecycle table, candidate accounts and a cross-tenant scheduler

- **Status:** Accepted
- **Date:** 2026-10-09
- **Sub-project:** SP-07a

## Context

- **PRD §24** turns a candidate, a job and a template version into an interview with nine fields, including its proctoring policy. **PRD §80** says an interview keeps the template version it was scheduled with.
- **PRD §25** lists the eight things an invitation tells the candidate; the master plan adds reminders, expiry, rescheduling and cancellation (§14 SP-07).
- **Master plan §7** fixes the interview's states: Scheduled → Invited → In Progress ⇄ Interrupted → Completed → Evaluating → Evaluated, or Expired, Cancelled, Abandoned.
- **Candidates sign in** to the desktop and the portal (SP-07b, SP-07c), so the invitation must create their account.
- **Reminders and expiry** are time-driven work that must find interviews in every organisation, but the application role sees one organisation at a time (ADR-0009).
- The product owner asked to build without pausing for decisions; these defaults can be revisited.

## Decision

- **An interview pins its rules.** It references `(template_id, template_version)` and copies, once, a `policy` snapshot (proctoring level and the checks it turns on, third eye, recording, coding, the mandatory system checks, the resume policy, the answer mode, `policy_version`) and the template version's pinned questions. Nothing later changes them.
- **One interview at a time per application**, held by a partial unique index over the active statuses. A cancelled, expired or abandoned interview frees the candidate for another.
- **A transition table is the only way to change status** (`lifecycle.TRANSITIONS`). Every move writes an `interview_events` row and an audit entry; reaching `in_progress` (from invited) and `completed` also queues `interview.started` and `interview.completed` for SP-18's webhooks, and creating one queues `interview.created`. Rescheduling an invited interview is `invited → invited`; re-running an evaluation is `evaluated → evaluating`.
- **Assignment rules:** the job is open; the stage isn't `uploaded` or `rejected`; the candidate has an email; the template is active (the chosen one, else the job's own interview template, PRD §11); the window closes after it opens, in the future, is at least the duration long and at most 30 days. Bulk assignment (up to 200) creates what passes and returns the rest with a code.
- **Scope:** an interview copies its job's team and recruiter, so ADR-0014's resource scope applies unchanged. Someone without `candidates.view` (the interviewer role) sees only interviews they review (`interview_reviewers`).
- **Candidate accounts** (`candidate_accounts`): one per candidate per organisation, created `invited` by the first email. Its single-use links (`candidate_tokens`: set password, reset) are stored as SHA-256 hashes; issuing one revokes the previous. Accounts and links are found before the tenant is known by `auth_candidate_by_email` and `auth_candidate_token`, SECURITY DEFINER functions owned by `hirevion_auth` (ADR-0013's pattern). One email may belong to candidates of several organisations, so the lookup returns up to ten accounts.
- **Candidate passwords need 12 characters** rather than 15: the device-bound key and the new-device code (SP-07c) are a second factor.
- **Invitations:** every email about an interview (invitation, reminder, reschedule, cancellation) is queued through the outbox and recorded as an `invitations` row holding §25's eight contents as sent. A candidate whose account is still invited gets a fresh set-password link each time; an active one is told to sign in. Times are shown in the interview's time zone (the organisation's by default), formatted for en-IN or en-US.
- **The scheduler** runs in the worker every 60 seconds. `scheduler_due_interviews(now, lead, limit)` lists what's due in every active organisation; it is a SECURITY DEFINER function owned by a new role, `hirevion_scheduler`, which can't log in, doesn't bypass row-level security and has read-only, all-rows policies on `interviews` and `organizations` only. Each due interview is then handled in its tenant's transaction under `FOR UPDATE SKIP LOCKED` and checked again, so concurrent workers never double-send. It reminds 24 hours before the window opens (when invited earlier than that) and 24 hours before an unstarted window closes, once each, and expires closed windows.
- **Application stages** gain `interview` (on invitation) and `interviewed` (on completion, SP-09); cancelling returns the application to `shortlisted`.
- **Permission:** `interviews.manage` (org admins and recruiters) creates, invites, reschedules, cancels and sets reviewers; `interviews.view` reads.
- **The organisation's support email** (`organizations.support_email`) is part of the profile; invitations fall back to `HV_SUPPORT_EMAIL`.

## Consequences

- **Reports can always show the rules an interview ran under**, and changing a template is safe at any time.
- **The isolation harness now audits `hirevion_scheduler`** alongside the other roles. SP-09 (abandonment) and SP-18 (notifications) extend the scheduler; each new cross-tenant listing must be another narrow SECURITY DEFINER function, never a wider role.
- **Invitation payloads hold a set-password link** until the mail consumer sends them, as recruiter invitations do (ADR-0013); SP-22's retention treats them as secrets.
- **Watch:** one person invited by several organisations has an account in each, with separate passwords; SP-07c's sign-in has to choose between them.
