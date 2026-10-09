# Hirevion — pending tasks

As of **2026-10-09**. What's left, in order, from the current build to the end of the plan.

- **Where to look:**
  - `MASTER_IMPLEMENTATION_PLAN.md` stays the source of truth: §14 for each sub-project's full deliverables, §15 for the schedule, Appendix A for PRD coverage.
  - This file says what to pick up next, and what the 2026-10-09 review found missing.
- **Keeping it current:** tick items as they land, and update §1 whenever a PR merges.

## 1. Where things stand

| Sub-project | State | Where |
|---|---|---|
| SP-00 Foundations & spikes | Merged | `main` |
| SP-01 Backend core (01a, 01b, 01c) | Merged | `main` |
| SP-02 Identity & access (02a, 02b) | Merged (MFA moved to SP-19) | `main` |
| SP-03 Web shell & design system | Merged | `main` |
| SP-04a Jobs & job descriptions | Done, CI green, **not merged** | PR #1 |
| SP-04b Resumes & candidates | Done, CI green, **not merged** | PR #2 (stacked on #1) |
| SP-05 Screening & ranking | Done, CI green, **not merged** | PR #3 (stacked on #2) |
| SP-06 Interview configuration | Done, CI green, **not merged** | PR #4 (stacked on #3) |
| SP-07 to SP-23 | Not started | — |

- **Checkpoints:**
  - CP0 is done.
  - CP1 is code-complete, but not merged, and its live AI evaluations are still pending.
  - CP2 to CP6 are open.
- **Progress:** 8 of about 35 build units are done (counting each split part).
- **What's left is the harder part:** the desktop app, the live voice interview, recording, proctoring and computer vision are all still ahead.

## 2. Your actions

- [ ] **Merge PRs #1 → #2 → #3 → #4, in that order.** All four are green. Until they land:
  - `main` stays at SP-02b;
  - every new branch stacks deeper;
  - nothing gets review feedback.
- [ ] **Replace `GEMINI_API_KEY` in `.env`.** The current key has been rejected since 2026-10-03. Then run:
  - `uv run hv eval-resumes` (targets: F1 ≥ 0.90 overall, ≥ 0.95 for contact fields);
  - `uv run hv eval-screening` (target: mean NDCG@10 ≥ 0.80);
  - `uv run pytest --live backend/core/tests/live`.

  **Recommended before SP-09 starts.** You chose to test with Gemini after the build, but the interview engine's latency target and its prompts can't be tuned on the mock, so this one check is worth doing early.
- [ ] **SP-00 hardware leftovers:** a real-phone third-eye test (`uv run hv eye-tunnel`) and a real-webcam media run.
- [ ] **Long-lead items** (master plan §17):
  - an OV code-signing certificate;
  - a domain;
  - an OpenAI organisation;
  - Deepgram DPAs;
  - counsel review of `docs/policies/` (arriving with H0.7);
  - the external pentest booking.
- [ ] **Choose how the lanes run (§5).** Recommended:
  - the desktop lane in a local session on this PC, since it needs Windows, webcams and Media Foundation;
  - the backend/web and AI lanes in separate sessions, local worktrees or Claude Code cloud.

## 3. Catch-up from the 2026-10-09 review

Things the plan promised that the build so far skipped. Each is small; do them before or alongside SP-07a.

- [ ] **H0.1 Job "Interview Template" field.** PRD §11 lists it as the job's 17th field, and Appendix A gave it to SP-06, which missed it. It needs:
  - `jobs.interview_template_id` (an active template);
  - a field on the job form;
  - pre-selection when assigning interviews.

  Lands in SP-07a.
- [ ] **H0.2 Dashboard KPIs from real data** (master plan SP-03: "wired in as modules land"):
  - now: open jobs, active candidates, screened, shortlisted;
  - with SP-07a: the interview KPIs;
  - the API: `GET /dashboard/summary`, within the reader's resource scope, taking the filters that already have data.
- [ ] **H0.3 Code review of PRs #1–#4.** §16 asks for a review of every sub-project, which was skipped. Run `/code-review` on each PR and fix the findings in follow-up commits.
- [ ] **H0.4 Missing CI gates** (master plan §9, §13, §16):
  - coverage: `pytest-cov` failing below 85% on `hirevion_core` domain modules, plus Vitest coverage;
  - Semgrep and Bandit;
  - osv-scanner over the Python, JS and Rust lockfiles;
  - `pip-licenses` and `license-checker` (Rust already has cargo-deny);
  - Trivy and a Syft SBOM for the API image.
- [ ] **H0.5 PRD traceability check** (§16): a script in CI that fails if an Appendix A row names no sub-project, or a done row points at code or tests that don't exist.
- [ ] **H0.6 Threat models** (§9: a STRIDE model per sub-project in `docs/security/`):
  - a catch-up file for SP-01–06: tenancy and RLS, sessions and CSRF, uploads and parsers, prompt injection, exports;
  - then one section per new sub-project.
- [ ] **H0.7 Policy drafts** (§10; SP-07b shows them): `docs/policies/` with privacy, recording, proctoring, data retention, the deletion process and the support contact. Marked as drafts for counsel.
- [ ] **H0.8 Live AI results:** after the new key, record the evaluation results in `docs/evals/`, and fix prompts that miss their targets.

## 4. Remaining sub-projects, in build order

Three lanes run side by side (master plan §15). Each part below is one PR, and each lands on `main` before the next part of the same lane starts. §14 of the master plan has every deliverable; the exit criteria here are the gates.

### Lane A — backend and web

Local, or a cloud session that has Postgres and Valkey.

- [ ] **SP-07a Interviews and invitations** (recruiter side; depends on SP-06).
  - **Interviews and their state machine:**
    - the states: scheduled, invited, in progress, interrupted, completed, evaluating, evaluated, expired, cancelled, abandoned;
    - an event history.
  - **Assignment:**
    - single and bulk: candidate + job + template version produce §24's nine fields, with a policy snapshot;
    - reviewers;
    - a "Create interview" action from the ranking, deferred from SP-05.
  - **Emails and scheduling:**
    - invitations with all eight §25 contents, in en-IN and en-US;
    - reminders, expiry, rescheduling and cancellation, from a small scheduler in the worker.
  - **Candidate accounts:** created on invitation, with a set-password link.
  - **Data and settings:**
    - a new `interviews.manage` permission;
    - application stages `interview` and `interviewed`, which fill the candidates' Interview and Completed tabs;
    - the organisation's support email;
    - H0.1.
  - **Pages:** `/interviews` (Upcoming, Live, Completed) and `/interviews/[id]`.
  - **Exit criteria:**
    - an invitation with all eight contents reaches Mailpit;
    - editing a template after assignment leaves the interview on its pinned version;
    - bulk assignment reports the candidates it skipped.
- [ ] **SP-07b Candidate portal** (depends on SP-07a).
  - **Sessions:** candidate sessions on the `candidate.` host, with an isolated `__Host-` cookie, CSRF, and a Caddy `/api` route.
  - **Sign-in:** invitation page → set password; sign in; reset password.
  - **Pages:**
    - interview status, windows and countdowns;
    - download page with system requirements;
    - notices: §83's ten disclosures and six policies, from H0.7;
    - a report placeholder until SP-17.
  - **Requests:** reschedule, support, accommodation, data rights and consent withdrawal, with a recruiter view.
  - **Exit criteria (Playwright):**
    - invitation email → set password → the interview is listed;
    - a reschedule request reaches the recruiter.
- [ ] **SP-07c Desktop candidate auth and releases** (depends on SP-07a).
  - **Login:** checks §28's six items.
  - **Device binding:**
    - an email one-time code on a new device (an organisation setting);
    - device-key registration (ES256 JWK);
    - DPoP proofs (RFC 9449) with a replay cache.
  - **Tokens:**
    - a 10-minute access JWT bound to the key (`cnf.jkt`);
    - a rotating refresh token (8 hours absolute; reuse revokes the whole family);
    - an interview-session token.
  - **Desktop releases:**
    - a release registry (channel, minimum version, rollout %, signatures);
    - the Tauri update manifest;
    - `/platform/desktop-releases`;
    - an outdated app answered with 426.
  - **Exit criteria:** a replayed proof, a stolen token without the device key, and an outdated version are each refused.
- [ ] **SP-18 Notifications and webhooks** (depends only on SP-01; can follow SP-07a). Takes over SP-07a's scheduler and the mail runner, and fills the notification centre.
  - **Exit criteria:**
    - the reference receiver verifies signatures;
    - retry and dead-letter work;
    - a replayed delivery is refused.
- [ ] **SP-19 Enterprise identity** (depends only on SP-02; any time): Entra ID, OIDC, SAML, SCIM, MFA (TOTP and recovery codes) and passkeys.
  - **Exit criteria:**
    - Keycloak and Entra test logins work;
    - SCIM compliance tests pass;
    - SAML signature wrapping is refused.
- [ ] **SP-17 Reports, review and Candidate 360** (after SP-10, SP-12 and SP-14).
  - **Deliverables:**
    - five report types, each as a web view and a PDF;
    - the review workspace;
    - the hiring statuses and the decision;
    - all thirteen Candidate 360 tabs;
    - the unified timeline;
    - moving cards on the pipeline board.
  - **Exit criteria:**
    - the CP3 golden path passes;
    - every report section is populated from a simulator run;
    - views, downloads and score changes are audited.
- [ ] **SP-20 ATS integrations and public API** (after SP-17 and SP-18).
  - **Exit criteria:**
    - contract tests pass for every adapter;
    - lint keeps provider logic out of the core;
    - API-key scope tests pass.
- [ ] **SP-21 Analytics and KPIs** (after SP-17).
  - **Exit criteria:**
    - every metric is defined and tested against seed data;
    - every chart passes axe.
- [ ] **SP-22 Administration and governance** (after SP-17).
  - **Deliverables:**
    - branding;
    - the AI configuration;
    - editable proctoring policies (from SP-06's presets);
    - retention, legal holds and DSR;
    - usage and cost pages;
    - server-backed saved views;
    - a people search beyond 2,000 users;
    - localisation packs.
  - **Exit criteria:**
    - retention respects holds, and deletions are audited;
    - the DSR bundle is complete;
    - every policy change is audited.

### Lane B — desktop and native

Local on this PC only: Windows, Rust, Tauri, webcams.

- [ ] **SP-08a Desktop foundation, part 1.** Can start now against a stub API; real sign-in arrives with SP-07c.
  - the Tauri app;
  - the `security` crate (CNG/TPM device key, DPAPI vault) and the `api-client` crate (DPoP);
  - the update gate;
  - all eleven §29 system checks, with their results stored.
- [ ] **SP-08b Desktop foundation, part 2:**
  - instructions, itemised consent and accommodations;
  - fullscreen and lockdown;
  - the interview UI shell: orb, captions, timer and controls;
  - the workspace host and the upload-drain screen;
  - NSIS installers for x64 and ARM64, development signing, GlitchTip, i18n and a11y.
  - **Exit criteria:**
    - the tauri-driver test passes: login → checks → consent → ready;
    - the app installs without admin rights;
    - updates are signature-verified;
    - a downgrade is refused.
- [ ] **SP-11 Native Windows monitoring** (after SP-08a).
  - **Exit criteria:**
    - each of these raises its event within 2 s: a capture-excluded window, a blocked process, a renamed blocked binary, a second monitor;
    - no keystroke content is ever logged.
- [ ] **SP-12 Recording pipeline** (after SP-08a; the server-side acknowledgement and the `media-worker` can go to lane A).
  - **Exit criteria:**
    - the chaos tests lose no acknowledged segment;
    - assembled tracks drift less than 100 ms.
- [ ] **SP-15a Computer vision core** (after SP-08a).
  - **Exit criteria:**
    - absent-face and multiple-face detection meet precision/recall on labelled clips;
    - CPU stays within budget while recording.
- [ ] **SP-13 Third-eye** (after SP-09 and SP-12).
  - **Exit criteria:**
    - pairing takes 60 s or less on iOS and Android;
    - a locked phone is flagged within 10 s;
    - a reused token is refused;
    - revoking kicks the old device.
- [ ] **SP-15b Advanced proctoring** (after SP-15a, SP-13 and SP-14).
  - **Exit criteria:**
    - each detector's precision/recall is reported;
    - false positives per 45-minute session stay within budget;
    - no signal is shown as proof.

### Lane C — AI and realtime

Can use a cloud session with the mock; live tuning needs the AI keys.

- [ ] **SP-09 AI interview engine.** The orchestration can start now, with the interview simulator as the client. Built in three parts:
  - **09a:** rooms, tokens and dispatch; the voice pipeline; the §35 state machine; the simulator;
  - **09b:** the nine orchestrator components, coverage, time control and text-answer mode;
  - **09c:** transcript artifacts, §91 events, checkpoints and crash recovery.
  - **Exit criteria:**
    - simulator personas finish full interviews;
    - p95 time to first audio ≤ 2.5 s;
    - a killed agent resumes within 10 s with no lost turns;
    - required skills are covered.
- [ ] **SP-10 Evaluation and AI governance** (after SP-09).
  - **Exit criteria:**
    - every score has verified evidence;
    - pinned re-runs reproduce within tolerance;
    - the eval gate blocks a regressed prompt.
- [ ] **SP-14 Proctoring engine and live monitoring** (after SP-09, SP-11 and SP-12).
  - **Exit criteria:**
    - p95 latency to the dashboard is under 1 s;
    - a reconnecting dashboard gets the alerts it missed;
    - dismissed events are audited and still reported.
- [ ] **SP-16 Coding interview** (after SP-09 and SP-08; the Monaco and whiteboard side is lane B).
  - **Exit criteria:**
    - the sandbox-escape suite holds;
    - all four languages run end to end;
    - time and memory are stored.

### Last

- [ ] **SP-23 Production hardening** (after everything else):
  - ASVS L2;
  - fuzzing;
  - AI-assisted pentest;
  - load tests;
  - backup and DR drills;
  - the §96 dashboards;
  - a WCAG audit, with a manual NVDA pass;
  - signing and the update pipeline;
  - support tooling;
  - the cost-model report;
  - the PRD §105 checklist.

### Owed by later sub-projects

Recorded in code as deferrals; listed so nothing is forgotten.

- **SP-07a:**
  - the "Create interview" action;
  - the candidates' Interview and Completed tabs;
  - interviews pinning a template version and its questions.
- **SP-09:** live use of question time limits and follow-up rules (SP-06 stores them).
- **SP-14 and SP-22:** proctoring presets become editable policies.
- **SP-17:** moving cards on the pipeline board; the remaining Candidate 360 tabs.
- **SP-18:** the notification centre's content; the scheduler taking over from SP-07a.
- **SP-19:** MFA, moved from SP-02.
- **SP-22:**
  - server-backed saved views;
  - a people search beyond 2,000 users;
  - usage pages and quota settings.

## 5. Schedule (re-planned 2026-10-09)

The original dates are in master plan §15. The build so far:

- **Pace:** one sub-project part per active day, one lane at a time.
- **Gaps:** no work happened on 2026-10-06 to 2026-10-08.

| CP | Outcome | Original (expected) | Re-plan, three lanes | Re-plan, one lane |
|---|---|---|---|---|
| 2 | A voice interview in the desktop app, with recording, core proctoring and evaluation | Oct 16 | Oct 24 | Nov 3 |
| 3 | The core hiring loop, live monitoring, reports and third-eye | Oct 22 | Nov 1 | Nov 15 |
| 4 | Coding, advanced proctoring, notifications and webhooks | Nov 5 | Nov 10 | Nov 27 |
| 5 | SSO/SCIM, ATS and public API, analytics, administration | Nov 17 | Nov 16 | Dec 6 |
| 6 | Hardened; the PRD §105 checklist green locally | Nov 28 | Nov 25 | Dec 15 |

- **Assumptions:**
  - work every day from 2026-10-10;
  - PRs merged within a day of going green;
  - the Gemini key fixed before SP-09;
  - you test each desktop build on real hardware.
- **Rule:** dates move; quality gates don't.

## 6. Definition of done for every remaining part

Corrected after the 2026-10-09 review.

1. **Plan:** a short plan in `docs/superpowers/plans/`, holding the decisions and the tasks.
2. **Tests first:** write failing tests, then the code. That includes the web components, where tests were written after the code in SP-06.
3. **Local checks:** ruff, mypy, Biome and tsc; the unit and DB tests; an end-to-end test of the part's main path.
4. **Review:** `/code-review` on the diff, with the findings fixed.
5. **Docs:**
   - the ADR;
   - the runbook;
   - the Appendix A rows;
   - the threat-model section;
   - this file.
6. **PR:** opened against `main`, never stacked more than one deep.
7. **Merge:** CI green, then you merge.

**Parallel lanes share some files.** Rules:

- **Migrations:** one linear Alembic chain, so renumber yours when rebasing onto `main`.
- **Generated files:** regenerate `openapi.json` and `schema.d.ts` after a rebase.
- **Message catalogues:** edit only your own namespace in the message files.
- **Permissions:** the permission catalogue changes only in lane A.

**Next up:** SP-07a (lane A), SP-08a (lane B), SP-09a (lane C).
