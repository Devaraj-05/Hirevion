# Hirevion — delivery plan to 2026-10-15

- **Readers:** the product owner (Devaraj-05) and every Claude Code session that builds a lane, in the cloud or on the local Windows PC.
- **Updated:** 2026-10-09, after SP-00 to SP-06 were merged to `main`.
- **Sources of truth:**
  - `MASTER_IMPLEMENTATION_PLAN.md` holds every part's full deliverables (§14) and PRD coverage (Appendix A).
  - This file holds who builds what, when, and how.

## 1. Goal

- **The target.** By the end of 2026-10-15 (IST), every remaining sub-project, SP-07 to SP-22 plus SP-23's automated parts, is:
  - built and tested;
  - merged to `main` with CI green;
  - covered by an automated run of the PRD §107 golden path on the mock AI.
- **No PRD feature is dropped.** If time runs short, finish in this order:

| Priority | What | Checkpoint |
|---|---|---|
| P0 | §104 MVP: interviews, candidate access, desktop, voice interview, recording, core proctoring, evaluation, live monitoring, reports, third-eye | CP2 + CP3 |
| P1 | Coding interview, advanced proctoring, notifications and webhooks | CP4 |
| P2 | SSO/SCIM, ATS and public API, analytics, administration and governance | CP5 |
| P3 | SP-23 automated hardening: load, fuzzing, ZAP, backup drills, dashboards, cost model | CP6 |

- **Outside what the agents can do.** These need you or a third party, and are scheduled from 2026-10-16:
  - live Gemini, Deepgram and OpenAI tuning, which needs your valid keys;
  - the desktop hardware matrix (webcams, two monitors, headset, Windows 10, N edition, low-spec laptop);
  - real phones for third-eye;
  - a manual NVDA accessibility pass;
  - certification: an Entra test tenant and the ATS vendor sandboxes (contract tests against mocks are in scope);
  - the code-signing certificate;
  - counsel review of `docs/policies/`;
  - the external pentest.

## 2. Where things stand

| Part | State |
|---|---|
| SP-00 to SP-06 (foundations, backend core, identity, web shell, jobs and resumes, screening, interview configuration) | Merged to `main` (PRs #1–#4 merged 2026-10-09) |
| Everything in section 7 | Not started |

## 3. The team: four lanes running at once

| Lane | Runs on | Builds |
|---|---|---|
| **A** Candidate access and reporting | Cloud session 1 | SP-07a, 07c, 07b, 18, 17, 21 |
| **B** Desktop and native | **The local Windows PC** (Tauri, Rust, webcams, Media Foundation) | SP-08a, then 11 + 12 (client) + 15a in parallel, then 08b, then the 16, 13 and 15b desktop parts |
| **C** Interview AI and realtime | Cloud session 2 | SP-09a, 09b, 09c, 10, 14, 16 (server), the vision agent (15a and 15b server) |
| **D** Quality, media services, identity and governance | Cloud session 3 | The H0 catch-up, SP-12 (server), 13, 19, 22, 20, 23 |

- **Models:**
  - Use the strongest model for the security-critical and complex parts: 07c, 09, 12, 13, 14, 16, 19.
  - A faster model is fine for documentation, CI configuration, i18n and simple CRUD pages.
- **Lane B also integrates.** It merges any green PR a cloud session couldn't merge itself (section 6).

## 4. Starting a cloud session

1. In Claude Code on the web, connect `github.com/Devaraj-05/Hirevion` and choose the branch `main`.
2. **Network access** must allow:
   - `pypi.org`, `files.pythonhosted.org`, `astral.sh`;
   - `registry.npmjs.org`, `nodejs.org`;
   - `github.com`, `objects.githubusercontent.com`;
   - the Ubuntu package mirrors.
3. **No secrets.** Sessions use the mock AI. Never paste API keys or passwords into a cloud session.
4. Paste the prompt below, with your lane's letter and name filled in.

```text
You are Lane <A|C|D> of the Hirevion build: <lane name from PENDING_TASKS.md section 3>.
1. Read CLAUDE.md, then PENDING_TASKS.md sections 5–8 and your lane in section 7. For each part,
   read only its MASTER_IMPLEMENTATION_PLAN.md §14 entry and the sections and ADRs it cites; grep
   the PRD for the cited § numbers instead of reading it whole.
2. Run `bash scripts/session-setup.sh` once (git identity, hooks, toolchains, services).
3. Build your lane's parts in order without stopping to ask: decide with sensible defaults and
   record each decision in the part's plan or ADR. Review your contracts (section 5) first.
4. Every part meets the definition of done and the merge protocol (section 6). Tick your own
   boxes in section 7 in the same PR.
5. Never wait idle: while CI runs, plan the next part; if a part waits on another lane, build
   against its contract and carry on.
6. Keep going until your lane is done. Report one short paragraph per merged part.
```

## 5. Contracts first

The desktop (lane B) calls APIs that other lanes build. **Lane B drafted all five contracts on 2026-10-09** in `docs/api/contracts/`. The README there holds the shared rules: DPoP-bound tokens, RFC 9457 error codes, server time and idempotent retries.

- **Review.** Each owning lane reviews its contract in its first hour, then implements it exactly.
- **Changes.** A change goes in a small PR that edits the contract and adds a dated line under its "Changes".
- **Lane B** codes against the contracts until the real endpoints merge.

| Contract file | Provider | Needed by lane B | Covers |
|---|---|---|---|
| `candidate-auth.md` | A (SP-07c) | Oct 11 | Login with §28's six checks, one-time code verify, device-key registration, refresh, logout, interview list; release check and update manifest |
| `interview-session.md` | C (SP-09a) | Oct 12 | Start (LiveKit URL and join token), text answer, complete, session state, clock sync, system-check results |
| `proctoring.md` | C (SP-14) | Oct 11 | Proctor session, batched signed and sequenced events (§67 schema), heartbeat, acknowledgements |
| `recordings.md` | D (SP-12) | Oct 11 | Segment upload URL, hash-verified acknowledgement, recovery listing |
| `third-eye.md` | D (SP-13) | Oct 12 | Issue the pairing QR, redeem, revoke, status events |

## 6. Rules for every part

**Definition of done:**

1. **Plan:** a short plan in `docs/superpowers/plans/` (decisions and the task list; no full code).
2. **Tests first:** failing tests first, then code. That covers backend, web components and Rust.
3. **Local checks:**
   - ruff, mypy, Biome, tsc and cargo clippy, for whatever you touched;
   - the tests you touched;
   - one end-to-end test of the part's main path.
4. **Review:** `/code-review` on the diff, with the findings fixed.
5. **Docs:**
   - the ADR, when a real decision was made;
   - the runbook section;
   - the Appendix A rows;
   - a threat-model section in `docs/security/threat-model.md`;
   - your boxes here.

**Merge protocol.** You may merge your own green PRs, by fast-forward only, so every commit stays authored and committed by Devaraj-05.

1. Branch `feat/sp-xx-<name>` from `origin/main`.
2. **Before the PR:**
   - `git fetch origin && git rebase origin/main`;
   - Alembic must show one head: renumber your migration after `main`'s head if needed;
   - regenerate `packages/api-client/openapi.json` (`uv run hv openapi`) and `schema.d.ts` (`pnpm --filter @hirevion/api-codegen generate`) if the API changed;
   - re-run the local checks.
3. **Open the PR.** Push the branch and open a PR to `main`. Run one background CI watcher that polls every 60–90 s; never poll by hand.
4. **Merge when CI is green:**

   ```bash
   git fetch origin
   git checkout -B main origin/main
   git merge --ff-only feat/sp-xx-<name>
   git push origin main
   ```

   If `main` moved in the meantime, rebase, `git push --force-with-lease` your own branch, wait for green, and retry.
5. **If the session can't push to `main`:** leave the PR green with the title prefix `[ready]`, and lane B merges it by fast-forward.
6. **Never:**
   - use GitHub's merge button (it makes GitHub the committer);
   - `--no-verify`;
   - force-push `main`;
   - add Co-Authored-By or any Claude attribution.

**Shared files.** Conflicts there are expected; resolve them like this:

- **Message catalogues** (`recruitment-platform/messages/*.json`): add only your own namespaces; on a conflict, keep both.
- **Permissions** (catalogue, the web's `permissions.ts`, labels) and the authorisation matrix's `EXPECTED` table: append your rows; on a conflict, keep both.
- **Router registrations** in `backend/api/src/hirevion_api/app.py`, and the route manifest: append; keep both.
- **Generated files:** never hand-merge them; regenerate after the rebase.
- **This file:** tick only your own lane's boxes.
- **ADR numbers:** each lane uses its own block, so numbers never collide: lane A 0020–0029, lane B 0018–0019 then 0050–0059, lane C 0030–0039, lane D 0040–0049. Add your row to `docs/architecture/adr/README.md` in number order; on a conflict, keep both.

**Saving credits:**

- **Read narrowly:** this file's sections, the part's §14 entry and the files you change. Search with grep instead of reading whole modules.
- **Compact at part boundaries:** run `/compact` after each merge, so the next part doesn't carry the old context.
- **Let CI do the heavy lifting:**
  - CI runs the full matrix, and only the jobs whose paths changed run on a branch.
  - Locally, run only the tests you touched, plus the part's own end-to-end spec.
- **Push sparingly:** when a part is ready, and once mid-part as a backup at most.
- **Don't touch what you didn't change:** no reformatting untouched files, no regenerating unchanged outputs, no rerunning green suites "just to check".
- **Subagents:** only for truly independent work; lane B's step B2 is the planned case.

## 7. The lanes, day by day

Dates are targets in IST. A box is ticked in the PR that merges the part.

### Lane A — candidate access and reporting (cloud session 1)

- [ ] **A0 (Oct 10, first hour):** review `docs/api/contracts/candidate-auth.md` and record any changes the way the contracts README says.
- [ ] **A1 SP-07a Interviews and invitations (Oct 10).**
  - **Interviews:**
    - the state machine (scheduled, invited, in progress, interrupted, completed, evaluating, evaluated, expired, cancelled, abandoned), with an event history;
    - single and bulk assignment producing §24's nine fields and a policy snapshot (pinning the template version);
    - reviewers.
  - **Invitations and scheduling:**
    - invitations with all eight §25 contents, in en-IN and en-US;
    - reminders, expiry, rescheduling and cancellation, from a scheduler loop in the worker.
  - **Candidate accounts:** created on invitation, with a set-password link.
  - **Data and settings:**
    - the `interviews.manage` permission;
    - application stages `interview` and `interviewed`;
    - the organisation's support email;
    - the job's "Interview Template" field (PRD §11, missed in SP-06).
  - **Pages:**
    - the ranking's "Create interview" action;
    - `/interviews` (Upcoming, Live, Completed) and `/interviews/[id]`;
    - the candidates' Interview and Completed tabs;
    - the interview KPIs on the dashboard.
  - **Exit criteria:**
    - the invitation reaches Mailpit with all eight contents;
    - editing the template afterwards leaves the interview on its pinned version;
    - bulk assignment reports what it skipped.
- [ ] **A2 SP-07c Desktop candidate auth and releases (Oct 10–11).**
  - **Login:** checks §28's six items.
  - **Device binding:**
    - an email one-time code on a new device (an organisation setting);
    - ES256 device-key registration;
    - DPoP (RFC 9449) with a replay cache in Valkey.
  - **Tokens:**
    - a 10-minute access JWT bound to the key (`cnf.jkt`);
    - a rotating refresh token (8 hours absolute; reuse revokes the family);
    - an interview-session token.
  - **Desktop releases:**
    - the release registry (channel, minimum version, rollout %, signatures);
    - the Tauri update manifest;
    - `/platform/desktop-releases`;
    - an outdated app answered with 426.
  - **Exit criteria:** a replayed proof, a stolen token without the key, and an outdated version are each refused.
- [ ] **A3 SP-07b Candidate portal (Oct 11).**
  - **Sessions:** on the `candidate.` host, with an isolated `__Host-` cookie, CSRF, the Caddy `/api` route, and the portal origin allowed.
  - **Sign-in:** invitation → set password; sign in; reset password.
  - **Pages:**
    - interviews with their windows and countdowns;
    - download and requirements;
    - notices: §83's ten disclosures and six policies, from lane D's drafts;
    - a report placeholder until A5.
  - **Requests:** reschedule, support, accommodation, data rights and consent withdrawal, with a recruiter view.
  - **Exit criterion (Playwright):** invitation email → set password → the interview is listed; a reschedule request reaches the recruiter.
- [ ] **A4 SP-18 Notifications and webhooks (Oct 12).**
  - **Notifications:**
    - §75's three channels and eight events;
    - per-user preferences;
    - the notification centre and the `/ws` notification channel.
  - **Webhooks:**
    - §77's nine events;
    - HMAC signatures, replay protection, retries, dead-letter, redelivery, secret rotation;
    - the SSRF-safe client;
    - the webhook admin page.
  - **The scheduler:** takes over A1's loop.
  - **Exit criteria:**
    - the reference receiver verifies signatures;
    - retry and dead-letter work;
    - a replayed delivery is refused.
- [ ] **A5 SP-17 Reports, review and Candidate 360 (Oct 13–14; needs C4, C5 and D2).**
  - **Reports:**
    - the interview (13 sections), proctoring (14), coding, internal candidate and candidate-visible reports;
    - each as a web view and a Playwright PDF.
  - **Review:**
    - the review workspace with a synced player and jumps to evidence;
    - notes and Hiring Manager input;
    - score changes;
    - §72's nine statuses and the human decision.
  - **Candidate 360:**
    - all thirteen tabs;
    - the unified timeline;
    - the pending-review queue;
    - moving cards on the pipeline board.
  - **Exit criteria:**
    - the CP3 golden path passes;
    - every report section is populated from a simulator run;
    - views, downloads and score changes are audited.
- [ ] **A6 SP-21 Analytics and KPIs (Oct 14–15).**
  - **Deliverables:**
    - §73's twelve analytics;
    - §74's funnel;
    - §106's twenty KPIs;
    - the bias view;
    - all ten dashboard KPIs and seven filters on real data;
    - CSV export.
  - **Exit criteria:**
    - every metric is defined and tested against seed data;
    - every chart passes axe.

### Lane B — desktop and native (the local Windows PC)

- [ ] **B1 SP-08a Desktop foundation, part 1 (Oct 10).**
  - **The Tauri app.**
  - **The `security` crate:**
    - a CNG/TPM device key;
    - a DPoP signer;
    - a DPAPI token vault;
    - environment sanitising and a debugger check;
    - a single instance.
  - **The `api-client` crate:** reqwest with rustls and DPoP, against `candidate-auth.md`.
  - **Startup:**
    - the update gate;
    - all eleven §29 system checks, with their results stored;
    - the sign-in screens, on a stub until A2 merges.
- [ ] **B2 in parallel, three subagents in worktrees (Oct 11–12):**
  - **SP-11 Native monitoring.** Exit criteria:
    - a capture-excluded window, a blocked or renamed process, and a second monitor each raise their event within 2 s;
    - no keystroke content is logged.
  - **SP-12 Client recording:**
    - Windows Graphics Capture → Media Foundation H.264 10-second segments;
    - WebCodecs camera and mic segments;
    - AES-GCM storage;
    - a resumable uploader against `recordings.md`.

    Exit criteria: the chaos tests lose no acknowledged segment; drift stays under 100 ms.
  - **SP-15a Computer vision on the device:**
    - a MediaPipe worker for the five face signals;
    - face-quality guidance during the system check.

    Exit criterion: CPU stays within budget.
- [ ] **B3 SP-08b Desktop foundation, part 2 (Oct 12–13).**
  - **Before the interview:** instructions, itemised consent and accommodations.
  - **The interview UI:**
    - fullscreen and lockdown;
    - the orb, captions, timer and controls;
    - joining the LiveKit room per `interview-session.md`;
    - the workspace host and the upload-drain screen.
  - **Packaging:**
    - NSIS installers for x64 and ARM64;
    - development signing and the signed updater;
    - GlitchTip;
    - i18n and a11y.
  - **Exit criteria:**
    - the tauri-driver test (login → checks → consent → ready) passes;
    - installs without admin rights;
    - updates are verified and a downgrade is refused.
- [ ] **B4 Desktop parts of SP-16, SP-13 and SP-15b (Oct 13–14):**
  - Monaco with a language picker, Run and Submit, the whiteboard, and §48's telemetry;
  - third-eye QR pairing and the placement guide;
  - gaze, pose and hands, phone and obstruction detection on the device.
- [ ] **B5 Windows golden path and chaos drills (Oct 15):**
  - kill the app, drop the network, unplug a device, fail an upload;
  - check the installer.

**B is also the integrator:** every few hours, merge `[ready]` PRs by fast-forward (section 6).

### Lane C — interview AI and realtime (cloud session 2)

- [ ] **C0 (Oct 10, first hour):** review `docs/api/contracts/interview-session.md` and `proctoring.md`; record any changes the way the contracts README says.
- [ ] **C1 SP-09a (Oct 10):**
  - rooms, least-privilege tokens and explicit agent dispatch;
  - the voice pipeline (Deepgram STT and TTS plugins, mock in CI);
  - §35's ten states;
  - `tools/interview-simulator` with its personas.
- [ ] **C2 SP-09b (Oct 11):**
  - §34's nine orchestrator components and twelve state fields;
  - per-question time limits and follow-up rules;
  - coverage and provenance;
  - the difficulty ladder and time control;
  - final questions from the FAQ;
  - text-answer mode;
  - guardrails.
- [ ] **C3 SP-09c (Oct 11–12):**
  - transcript segments and artifacts (JSON, VTT, TXT);
  - §91's events over `realtime`;
  - per-turn checkpoints, the resume policy and crash recovery.
  - **Exit criteria:**
    - every persona finishes a full interview;
    - a killed agent resumes within 10 s;
    - required skills are covered.
- [ ] **C4 SP-10 Evaluation and AI governance (Oct 12).**
  - **Deliverables:**
    - the live AnswerAnalyzer and the async evaluator over §44's eight dimensions, each score with evidence;
    - skill and final evaluations;
    - pinned re-runs;
    - the eval harness gate in CI;
    - the human-calibration workflow.
  - **Exit criteria:**
    - every score has verified evidence;
    - re-runs reproduce;
    - a regressed prompt is blocked.
- [ ] **C5 SP-14 Proctoring engine and live monitoring (Oct 13).**
  - **Deliverables:**
    - the §54 pipeline and §67 schema;
    - the severity table and rule engine;
    - the evidence manager;
    - state observed by the server (LiveKit webhooks, upload continuity, heartbeats);
    - alerts and nudges;
    - event review;
    - the live dashboard on `/ws/proctoring`.
  - **Exit criteria:**
    - p95 latency to the dashboard is under 1 s;
    - a reconnect gets the missed alerts;
    - dismissed events are audited.
- [ ] **C6 SP-16 Coding, server side (Oct 14).**
  - **Deliverables:**
    - `sandbox-runner` (a fresh hardened container per run) and `coding-service`;
    - the Python, Node, TypeScript and SQL runners;
    - question tests;
    - CodingController;
    - §47's evaluation;
    - the coding report data.
  - **Exit criteria:**
    - the sandbox-escape suite holds;
    - all four languages run end to end.
- [ ] **C7 Vision agent (Oct 14–15):**
  - SP-15a's server-side checks of face events;
  - SP-15b's third-eye analysis, speech analytics, extra-speaker detection and cross-camera correlation.
  - **Exit criteria:**
    - each detector's precision and recall is reported on the labelled set;
    - no signal is shown as proof.

### Lane D — quality, media services, identity and governance (cloud session 3)

- [ ] **D0 (Oct 10, first hour):** review `docs/api/contracts/recordings.md` and `third-eye.md`; record any changes the way the contracts README says.
- [ ] **D1 Catch-up H0 (Oct 10). Things the plan promised and SP-04a to SP-06 skipped.**
  - **Policy drafts:** `docs/policies/` with privacy, recording, proctoring, data retention, the deletion process and the support contact. **Do this first: A3 needs them.**
  - **CI gates:**
    - coverage: `pytest-cov` failing below 85% on `hirevion_core` domain modules, plus Vitest coverage;
    - Semgrep and Bandit;
    - osv-scanner over all the lockfiles;
    - `pip-licenses` and `license-checker`;
    - Trivy and a Syft SBOM for the API image.
  - **Traceability:** a CI check that every Appendix A row names a sub-project and points at existing code and tests.
  - **Threat models:** `docs/security/threat-model.md`, covering SP-01 to SP-06.
  - **Code review:** `/code-review` over the SP-04a to SP-06 code, with the findings fixed.
  - **Dashboard:** KPIs from real data for jobs and candidates.
- [ ] **D2 SP-12 Server side (Oct 11).**
  - **Deliverables:**
    - segment upload URLs (write-only, per blob, 15 minutes);
    - hash-verified acknowledgement;
    - `media-worker` (ffmpeg as a separate process) assembling the tracks and the timeline map;
    - Egress for the conversation audio and third-eye;
    - evidence snapshots;
    - audited playback URLs;
    - `RECORDING_STATUS`;
    - §85's storage layout.
- [ ] **D3 SP-13 Third-eye (Oct 12).**
  - **Deliverables:**
    - pairing tokens: short-lived, single-use, bound to the interview and the candidate;
    - a publish-only LiveKit token;
    - the `third-eye/` mobile web app (permissions, placement guide, Wake Lock, reconnect);
    - status events;
    - revocation.
  - **Exit criteria:**
    - a reused token is refused;
    - revoking kicks the old device;
    - a locked phone is flagged within 10 s.
- [ ] **D4 SP-19 Enterprise identity (Oct 13).**
  - **Deliverables:**
    - Entra ID, OIDC and SAML per organisation;
    - home-realm discovery and just-in-time provisioning;
    - SCIM 2.0;
    - TOTP MFA with recovery codes;
    - passkeys;
    - SSO-only mode.
  - **Exit criteria:**
    - Keycloak logins work;
    - SCIM compliance passes;
    - SAML signature wrapping is refused.
- [ ] **D5 SP-22 Administration and governance (Oct 13–14).**
  - **Deliverables:**
    - branding;
    - the AI configuration;
    - editable proctoring policies;
    - the app category catalogue;
    - retention with legal holds;
    - DSR and consent tooling;
    - usage, cost and quotas;
    - server-backed saved views;
    - a people search;
    - the platform pages;
    - localisation packs.
  - **Exit criteria:**
    - retention respects holds;
    - the DSR bundle is complete;
    - every change is audited.
- [ ] **D6 SP-20 ATS integrations and public API (Oct 14–15; the results sync needs A5).**
  - **Deliverables:**
    - a provider-neutral adapter;
    - adapters for custom REST, webhooks, Greenhouse, Lever, Workday, SuccessFactors, Oracle and iCIMS;
    - contract tests against local mocks;
    - scoped API keys;
    - rate limits;
    - the published docs.
- [ ] **D7 SP-23 automated hardening (Oct 15).**
  - **Deliverables:**
    - the §107 golden-path test on the mock, using lane C's simulator;
    - k6 load;
    - parser fuzzing;
    - a ZAP baseline;
    - a backup and restore script and drill;
    - §96's dashboards and alerts;
    - performance budgets;
    - runbooks;
    - the cost-model report;
    - the §105 checklist status.

## 8. Checkpoints

| When (IST) | Checkpoint | What shows it |
|---|---|---|
| Oct 12, evening | **CP2** | A simulator persona completes a voice interview on the mock (C), with recording acknowledged (D2) and evaluation (C4). The desktop goes from login to "Ready" against the real candidate auth (A2 + B1). |
| Oct 13, evening | **CP3** | Interviews, the portal, third-eye, live monitoring and reports: the §104 MVP end to end. |
| Oct 14, evening | **CP4** | Coding, advanced proctoring, notifications and webhooks. |
| Oct 15, evening | **CP5 + CP6 (automated)** | SSO/SCIM, ATS and public API, analytics, administration; the golden path and every CI gate green. |

- **Morning report.** Lane B posts one each day: what merged, what's red, and which lane is at risk. A slipping lane drops to its next-lowest-priority part, never its P0 work.

## 9. Your part

- **Now:** start the three cloud sessions (section 4).
- **Keep this PC available for lane B:**
  - leave it on and stop it from sleeping;
  - keep Docker Desktop running;
  - keep Claude Code running in the repo.
- **Fix `GEMINI_API_KEY`** in the local `.env` (never in a cloud session). The live checks run on this PC once the build is done:
  - `uv run hv eval-resumes`;
  - `uv run hv eval-screening`;
  - `uv run pytest --live backend/core/tests/live`;
  - the interview latency benchmark.
- **Each day, about 10 minutes:**
  - skim section 7's boxes and the morning report;
  - check that CI on `main` is green.
- **From Oct 16:** the hardware, phone, NVDA and live-vendor checks in section 1, plus the long-lead items:
  - the code-signing certificate;
  - a domain;
  - the OpenAI organisation;
  - the Deepgram DPA;
  - counsel review;
  - booking the pentest.

## 10. Deferrals recorded in code, so nothing is lost

- **A1 (SP-07a):**
  - the "Create interview" action;
  - the candidates' Interview and Completed tabs;
  - interviews pinning a template version and its questions.
- **C2 (SP-09b):** live use of question time limits and follow-up rules (SP-06 stores them).
- **C5 (SP-14) and D5 (SP-22):** proctoring presets become editable policies.
- **A5 (SP-17):** moving cards on the pipeline board; the remaining Candidate 360 tabs.
- **A4 (SP-18):** the notification centre's content; the scheduler.
- **D4 (SP-19):** MFA, moved from SP-02.
- **D5 (SP-22):**
  - server-backed saved views;
  - a people search beyond 2,000 users;
  - usage pages and quota settings.
