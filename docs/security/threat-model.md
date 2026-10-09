# Threat model

- **Readers:** whoever changes a sub-project's trust boundaries, and the reviewers of the pentest scope (master plan §9, §16).
- **Method:** STRIDE per sub-project: what it protects, where its trust boundaries are, each threat with the control that answers it, and what's left (residual risk). Each part adds its section in the PR that builds it (PENDING_TASKS.md §6).
- **Shared controls** every section relies on, not repeated below:
  - row-level security per organisation, forced, with the isolation harness in CI (ADR-0009);
  - server-side sessions with CSRF and `__Host-` cookies (ADR-0013);
  - permission guards on every route, checked by the authorisation matrix (ADR-0014);
  - the hash-chained, append-only audit log (ADR-0009);
  - RFC 9457 errors that never echo internals (ADR-0010).

## SP-07a Interviews and invitations

**Assets:** interviews and their pinned policies; candidates' email addresses; set-password links; the invitation contents; the scheduler's cross-organisation view.

**Trust boundaries:** recruiter browser → API; API → outbox → mail consumer → SMTP → candidate inbox; the scheduler's SECURITY DEFINER listing across organisations.

| Threat (STRIDE) | Example | Control |
|---|---|---|
| Spoofing | Someone uses a forwarded invitation to set the candidate's password | Single-use 256-bit links, stored hashed, expiring (7 days); each new email revokes the previous link; claiming happens inside the transaction that sets the password (SP-07b), so two uses can't both win |
| Tampering | A recruiter edits the template after scheduling to change an interview's rules | The interview pins the template version and copies the policy once; versions are insert-only (ADR-0017) |
| Tampering | A recruiter assigns an interview for a job outside their teams | Assignment loads applications through the resource scope; out-of-scope ones are skipped as `application-not-found` |
| Repudiation | "I never cancelled that interview" | Every status change is an `interview_events` row and an audit entry with the acting user, IP and user agent; reschedules and cancellations keep their reason |
| Information disclosure | An interviewer browses every interview | Without `candidates.view`, reads are limited to interviews the user reviews; other organisations' interviews are invisible through RLS |
| Information disclosure | The scheduler role leaks data across tenants | `hirevion_scheduler` can't log in and doesn't bypass RLS; its only grant is SELECT on `interviews` and `organizations` through one function that returns ids; the isolation harness audits the role |
| Information disclosure | Invitation emails reveal internal data | Emails carry only the company, job, window, instructions, requirements, notice and support links; domain events carry ids and status only |
| Denial of service | Bulk assignment of thousands of candidates | At most 200 per request; per-IP rate limits; the outbox decouples sending |
| Denial of service | Two workers send the same reminder twice | Due interviews are re-checked under `FOR UPDATE SKIP LOCKED`, and the sent-at stamp commits with the queued email |
| Elevation of privilege | A hiring manager cancels interviews | `interviews.manage` is held only by org admins and recruiters; the matrix test pins every route's permission |

**Residual risks:**
- A candidate's mailbox is the root of their account; a compromised mailbox lets someone set the password before them. SP-07c's new-device code and device-bound key limit what that buys.
- Set-password links wait in `outbox_events` payloads until sent; SP-22's retention must purge them.
