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

## SP-07c Candidate desktop sign-in and releases

**Assets:** candidate passwords; access, session and refresh tokens; device keys; one-time codes; the token signing key; the release registry and what the updater installs.

**Trust boundaries:** the desktop app on the candidate's machine (untrusted) → API; email (codes); the update bundles' host → the desktop's updater.

| Threat (STRIDE) | Example | Control |
|---|---|---|
| Spoofing | A token copied from the desktop's memory or a log is used from another machine | Every token is bound to the device key (`cnf.jkt`); every request needs a fresh DPoP proof from that key; the private key never leaves the device (TPM where available) |
| Spoofing | A captured proof is replayed | `jti` remembered per key for 5 minutes in Valkey; `iat` within ±60 s; `htm`/`htu` bind it to one request; `ath` binds it to one token |
| Spoofing | Password guessing or stuffing | argon2id; the same answer for unknown emails after the same work; progressive lockout per email (`423`); per-IP and per-email limits that fail closed |
| Spoofing | A stolen password on a new machine | The emailed new-device code (on by default), only answerable by the key that asked, 5 attempts, 10 minutes |
| Tampering | A refresh token is stolen and used before the real app | Rotation on every use; a spent token coming back revokes the whole family, killing the thief's tokens too; refresh also needs the device's proof |
| Tampering | An old, vulnerable app keeps signing in | The channel's minimum version is checked at sign-in and refresh (`426`) |
| Tampering | A malicious or older update is pushed | Releases carry a minisign signature the desktop's updater verifies; the manifest never offers a version at or below the running one; registry changes need a super admin with step-up and are audited |
| Repudiation | "I never signed in from that computer" | Audit entries per account: sign-in, failure, lockout, codes sent and verified, device registered, refresh, reuse, sign-out, session tokens |
| Information disclosure | Sign-in reveals which emails are candidates | Identical refusals; the masked address (`a***@domain`) is shown only after the password is right |
| Information disclosure | A session token is used for another interview | The token names one interview; interview routes compare it with the path |
| Denial of service | Flooding codes to a candidate's inbox | A resend at most every 60 s and 5 per challenge; per-IP limits |
| Elevation of privilege | An access token used where a session token is needed, or the reverse | `scope` is checked on every verification |

**Residual risks:**
- A device without a TPM keeps its key in the software store; malware with the user's privileges can use it while it runs. SP-11's integrity checks and SP-14's server-side signals are the backstop.
- Rotating the signing key signs everyone out; the cloud plan adds overlapping keys.

## SP-09 The interview engine

**Assets:**
- the interview's questions and their expected concepts (the answer key);
- the candidate's answers, voice and transcript;
- the live analysis;
- the engine's checkpoint;
- consent and system-check records;
- the LiveKit API secret and participant tokens;
- the organisation's FAQ.

**Trust boundaries:**
- the desktop app on the candidate's machine (untrusted) → API and LiveKit;
- the candidate's words → the analysis model (prompt injection);
- LiveKit → the API's webhook;
- the interview agent (a trusted backend worker) → the database and Valkey;
- the recruiter's browser → the live events websocket.

| Threat (STRIDE) | Example | Control |
|---|---|---|
| Spoofing | Someone joins the interview's room as the candidate, or as the agent | Room tokens are minted only by the API, after the session token and its DPoP proof; the candidate's token names one room and one identity; agents join only by explicit dispatch carrying the interview in metadata the API wrote |
| Spoofing | A forged webhook interrupts or ends someone's interview | Deliveries must carry LiveKit's JWT over the body's SHA-256, signed with the API secret; the room's metadata must name the same interview as its name; handlers are idempotent |
| Spoofing | A cross-site page opens the live events socket with the recruiter's cookie | The handshake must come from an allowed Origin, with a live session that has `interviews.view` and reaches the interview; it's checked again every minute |
| Tampering | The candidate's answer tells the model to mark it excellent or to reveal the answer key | Deterministic manipulation intents are caught before any model sees the text, answered neutrally, flagged and never counted as an answer; the answer goes to the model as JSON data under a prompt that says so; the model's own manipulation flag is a second opinion |
| Tampering | A model is induced to speak the expected concepts or a score | Model-written text passes an output guard (a short question, no markdown, no score, rating or "correct answer") or a template is spoken; expected concepts are never sent to the desktop |
| Tampering | Two processes take turns at once and corrupt the interview | A Valkey turn lock per interview, an optimistic `state_seq` on every save (checked against the seq read before the model calls), and one agent per interview (an expiring agent lock) |
| Tampering | The participant token publishes something other than its camera, microphone and screen preview, or changes its own metadata | Grants limited to those three sources and data; no room create, admin, record or metadata changes |
| Tampering | An accommodation is granted mid-interview to stretch the time or switch to typed answers | Decisions need `interviews.manage`, are audited, and are refused once the interview has started |
| Repudiation | "I never agreed to be recorded" | Consents are insert-only rows of each purpose against the notice's version, with IP and user agent; a notice whose wording changed has a new version and old consents are refused |
| Repudiation | "The AI asked me something it shouldn't have" | Every question is stored with its source and reference (library version, resume quote and page, rule or template), and both sides of the conversation are kept in the transcript and its artifacts with SHA-256 |
| Information disclosure | Live events or the transcript reach someone outside the interview's team | The transcript route uses the resource scope (reviewers only theirs); events carry text and timing but no scores; transcript files are reached only by short-lived download URLs |
| Information disclosure | The candidate's name or contact details reach a model | The analysis and follow-up calls carry the question, the skill, the concepts and the answer only; greetings use the first name locally |
| Information disclosure | The AI makes up company facts in final questions | Final questions are answered only from the organisation's FAQ by deterministic matching; anything else is passed on |
| Denial of service | A script floods answers to burn model calls | 30 answers a minute per interview (after the token is checked) and a per-IP ceiling; analysis has a 4 s budget and falls back to the heuristic |
| Denial of service | The candidate never comes back, holding an agent and a room | The resume grace and interruption limit; the scheduler abandons the interview after the grace; the room empties after 10 minutes |
| Elevation of privilege | A text answer or chat message drives the agent | The agent takes no chat input (`text_input` off); typed answers go only through the API with the session token |

**Residual risks:**
- The deterministic manipulation patterns are English and phrase-based; a paraphrased injection can still reach the analysis model, which only steers the next question. SP-10's evaluator must treat answers as untrusted in the same way.
- Integrity flags (AI-sounding text, repeated answers) are signals for a reviewer, never proof; a candidate can paraphrase.
- LiveKit can't restrict which data topics a participant sends on; the agent ignores everything but `hv.control`'s three actions.
