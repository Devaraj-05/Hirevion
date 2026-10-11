# Hirevion — delivery plan

- **Readers:** the product owner (Devaraj-05) and every Claude Code session or subagent that builds a part.
- **Sources of truth:**
  - `MASTER_IMPLEMENTATION_PLAN.md` holds every part's full deliverables (§14) and PRD coverage (Appendix A).
  - This file holds the order, the dependencies, the exit criteria and the rules.
  - `docs/STATUS.md` holds what is merged, what is in progress and what blocks.

## 1. Goal

- **The target.** Every remaining sub-project, SP-07 to SP-22 plus SP-23's automated parts, is:
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

- **Outside what the agents can do.** These need you or a third party, after the build:
  - live Gemini, Deepgram and OpenAI tuning, which needs your valid keys;
  - the desktop hardware matrix (webcams, two monitors, headset, Windows 10, N edition, low-spec laptop);
  - real phones for third-eye;
  - a manual NVDA accessibility pass;
  - certification: an Entra test tenant and the ATS vendor sandboxes (contract tests against mocks are in scope);
  - the code-signing certificate;
  - counsel review of `docs/policies/`;
  - the external pentest.

## 2. Where things stand

See [docs/STATUS.md](docs/STATUS.md).

## 3. The team

- **Every lane runs on the local Windows PC.** The main session coordinates; parts run as background subagents in git worktrees. Everything merges into `main`.
- **Pace.** The account's usage limit, which resets about every five hours, sets the pace more than the number of agents.
  - Run about three subagents at a time.
  - Give each a narrow brief.
  - Resume a stopped subagent instead of restarting it, so its context isn't rebuilt.

| Lane | Builds |
|---|---|
| **A** Candidate access and reporting | SP-07a, 07c, 07b, 18, 17, 21 |
| **B** Desktop and native (needs Windows: Tauri, Rust, webcams, Media Foundation) | SP-08a, then 11 + 12 (client) + 15a in parallel, then 08b/08c, then the 16, 13 and 15b desktop parts |
| **C** Interview AI and realtime | SP-09a, 09b, 09c, 10, 14, 16 (server), the vision agent (15a and 15b server) |
| **D** Quality, media services, identity and governance | The H0 catch-up, SP-12 (server), 13, 19, 22, 20, 23 |

- **Models:**
  - Use the strongest model for the security-critical and complex parts: 07c, 09, 12, 13, 14, 16, 19.
  - A faster model is fine for documentation, CI configuration, i18n and simple CRUD pages.
- **The main session integrates.** It merges any green PR a subagent couldn't merge itself (section 5).

## 4. Contracts first

The desktop calls APIs that other lanes build. The five contracts live in `docs/api/contracts/`. The README there holds the shared rules: DPoP-bound tokens, RFC 9457 error codes, server time and idempotent retries.

- **Review.** Each owning lane reviews its contract first, then implements it exactly.
- **Changes.** A change goes in a small PR that edits the contract and adds a line under its "Changes".
- **The desktop** codes against the contracts until the real endpoints merge.

| Contract file | Provider | Covers |
|---|---|---|
| `candidate-auth.md` | A (SP-07c) | Login with §28's six checks, one-time code verify, device-key registration, refresh, logout, interview list; release check and update manifest |
| `interview-session.md` | C (SP-09a) | Start (LiveKit URL and join token), text answer, complete, session state, clock sync, system-check results |
| `proctoring.md` | C (SP-14) | Proctor session, batched signed and sequenced events (§67 schema), heartbeat, acknowledgements |
| `recordings.md` | D (SP-12) | Segment upload URL, hash-verified acknowledgement, recovery listing |
| `third-eye.md` | D (SP-13) | Issue the pairing QR, redeem, revoke, status events |

## 5. Rules for every part

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
   - your box here, and `docs/STATUS.md`.

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
5. **If a subagent can't push to `main`:** leave the PR green with the title prefix `[ready]`, and the main session merges it by fast-forward.
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
- **This file:** tick only your own part's box.
- **ADR numbers:** each lane uses its own block, so numbers never collide: lane A 0020–0029, lane B 0018–0019 then 0050–0059, lane C 0030–0039, lane D 0040–0049. Add your row to `docs/architecture/adr/README.md` in number order; on a conflict, keep both.

**Saving credits:**

- **Read narrowly:** this file's sections, the part's §14 entry and the files you change. Search with grep instead of reading whole modules.
- **Compact at part boundaries:** run `/compact` after each merge, so the next part doesn't carry the old context.
- **Let CI do the heavy lifting:**
  - CI runs the full matrix, and only the jobs whose paths changed run on a branch.
  - Locally, run only the tests you touched, plus the part's own end-to-end spec.
- **Push sparingly:** when a part is ready, and once mid-part as a backup at most.
- **Don't touch what you didn't change:** no reformatting untouched files, no regenerating unchanged outputs, no rerunning green suites "just to check".
- **Subagents:** one per independent part, about three at a time (section 3).

## 6. The parts

A box is ticked in the PR that merges the part. Deliverables are in MASTER §14; only what §14 doesn't say is written here.

### Lane A — candidate access and reporting

- [x] **A0** Review `docs/api/contracts/candidate-auth.md`. Depends on: nothing.
- [x] **A1 SP-07a Interviews and invitations.** Depends on: SP-02, SP-06. See MASTER §14 SP-07.
  - Exit: the invitation reaches Mailpit with all eight contents; editing the template afterwards leaves the interview on its pinned version; bulk assignment reports what it skipped.
- [x] **A2 SP-07c Desktop candidate auth and releases.** Depends on: A1. See MASTER §14 SP-07.
  - Exit: a replayed proof, a stolen token without the key, and an outdated version are each refused.
- [ ] **A3 SP-07b Candidate portal.** Depends on: A1, D1 policy drafts. See MASTER §14 SP-07 (§6.3).
  - Exit (Playwright): invitation email → set password → the interview is listed; a reschedule request reaches the recruiter.
- [ ] **A4 SP-18 Notifications and webhooks.** Depends on: SP-01, A1 (takes over A1's scheduler loop). See MASTER §14 SP-18.
  - Exit: the reference receiver verifies signatures; retry and dead-letter work; a replayed delivery is refused.
- [ ] **A5 SP-17 Reports, review and Candidate 360.** Depends on: C4, C5, D2. See MASTER §14 SP-17.
  - Exit: the CP3 golden path passes; every report section is populated from a simulator run; views, downloads and score changes are audited.
- [ ] **A6 SP-21 Analytics and KPIs.** Depends on: A5. See MASTER §14 SP-21.
  - Exit: every metric is defined and tested against seed data; every chart passes axe.

### Lane B — desktop and native (the local Windows PC)

- [x] **B1 SP-08a Desktop foundation, part 1.** Depends on: `candidate-auth.md`. See MASTER §14 SP-08.
- [x] **B2 SP-11, SP-12 client, SP-15a desktop**, three subagents in parallel. Depends on: B1. See MASTER §14 SP-11, SP-12, SP-15a.
  - Exit SP-11: a capture-excluded window, a blocked or renamed process, and a second monitor each raise their event within 2 s; no keystroke content is logged.
  - Exit SP-12 client: the chaos tests lose no acknowledged segment; drift stays under 100 ms.
  - Exit SP-15a desktop: CPU stays within budget.
- [ ] **B3 SP-08b/08c Desktop foundation, part 2.** Depends on: B2, C1. See MASTER §14 SP-08.
  - Interview path and services are merged. Still open (SP-08c): packaging, the workspace host for code and whiteboard (with C6), and the third-eye status in heartbeats (`not_required` until D3).
  - Exit: the tauri-driver test (login → checks → consent → ready) passes; installs without admin rights; updates are verified and a downgrade is refused.
- [ ] **B4 Desktop parts of SP-16, SP-13 and SP-15b.** Depends on: B3, C6, D3. See MASTER §14 SP-16, SP-13, SP-15b.
  - Exit: as in those §14 entries, for the desktop side.
- [ ] **B5 Windows golden path and chaos drills.** Depends on: B3, B4. See MASTER §16 (chaos drills).
  - Exit: kill the app, drop the network, unplug a device, fail an upload — each ends with complete recordings, the right events and the interview resumed; the installer checks pass.

### Lane C — interview AI and realtime

- [x] **C0** Review `interview-session.md` and `proctoring.md`. Depends on: nothing.
- [x] **C1–C3 SP-09a–c AI interview engine.** Depends on: SP-01, SP-06, A1. See MASTER §14 SP-09.
  - Exit: every persona finishes a full interview; a killed agent resumes within 10 s; required skills are covered. The voice p95 is measured on this PC with `hv-voice-bench`.
- [x] **C4 SP-10 Evaluation and AI governance.** Depends on: C3. See MASTER §14 SP-10.
  - Exit: every score has verified evidence; re-runs reproduce; a regressed prompt is blocked.
- [x] **C5 SP-14 Proctoring engine and live monitoring.** Depends on: C3, B2, D2. See MASTER §14 SP-14.
  - Also (moved from D2): evidence snapshots, screen and camera at event time, asked for by SP-14's events.
  - Exit: p95 latency to the dashboard is under 1 s; a reconnect gets the missed alerts; dismissed events are audited.
- [ ] **C6 SP-16 Coding, server side.** Depends on: C3. See MASTER §14 SP-16.
  - Exit: the sandbox-escape suite holds; all four languages run end to end.
- [ ] **C7 Vision agent (SP-15a and SP-15b server).** Depends on: C5, D3. See MASTER §14 SP-15a, SP-15b.
  - Exit: each detector's precision and recall is reported on the labelled set; no signal is shown as proof.

### Lane D — quality, media services, identity and governance

- [x] **D0** Review `recordings.md` and `third-eye.md`. Depends on: nothing.
- [ ] **D1 Catch-up H0** (what SP-04a to SP-06 skipped). Depends on: nothing. Plan: `docs/superpowers/plans/2026-10-09-h0-catch-up.md`.
  - [x] Policy drafts in `docs/policies/`.
  - [ ] CI gates: `pytest-cov` failing below 85% on `hirevion_core` domain modules, plus Vitest coverage; Semgrep and Bandit; osv-scanner over all the lockfiles; `pip-licenses` and `license-checker`; Trivy and a Syft SBOM for the API image.
  - [x] Traceability: `hv trace --check`, run in CI.
  - [x] Threat models for SP-01 to SP-06.
  - [ ] Code review: `/code-review` over the SP-04a to SP-06 code, with the findings fixed.
  - [ ] Dashboard: KPIs from real data (PRD §10) for jobs and candidates.
- [x] **D2 SP-12 Server side.** Depends on: SP-01, `recordings.md`. See MASTER §14 SP-12. Plan: `docs/superpowers/plans/2026-10-10-sp-12-server-recording.md`.
  - Exit: as in MASTER §14 SP-12 (with B2's client). Egress moved to D3, evidence snapshots to C5.
- [ ] **D3 SP-13 Third-eye.** Depends on: C3, D2. See MASTER §14 SP-13.
  - Also (moved from D2): LiveKit Egress of the conversation audio and the third-eye video.
  - Exit: a reused token is refused; revoking kicks the old device; a locked phone is flagged within 10 s.
- [ ] **D4 SP-19 Enterprise identity** (includes TOTP MFA, moved from SP-02). Depends on: SP-02. See MASTER §14 SP-19.
  - Exit: Keycloak logins work; SCIM compliance passes; SAML signature wrapping is refused.
- [ ] **D5 SP-22 Administration and governance.** Depends on: A5, C5. See MASTER §14 SP-22.
  - Exit: retention respects holds; the DSR bundle is complete; every change is audited.
- [ ] **D6 SP-20 ATS integrations and public API.** Depends on: A4, A5. See MASTER §14 SP-20.
  - Exit: as in MASTER §14 SP-20.
- [ ] **D7 SP-23 Automated hardening.** Depends on: everything above. See MASTER §14 SP-23.
  - Exit: the §107 golden-path test passes on the mock (with C's simulator); every CI gate is green; the §105 checklist status is recorded.

## 7. Checkpoints

| Checkpoint | What shows it |
|---|---|
| **CP2** | A simulator persona completes a voice interview on the mock (C), with recording acknowledged (D2) and evaluation (C4). The desktop goes from login to "Ready" against the real candidate auth (A2 + B1). |
| **CP3** | Interviews, the portal, third-eye, live monitoring and reports: the §104 MVP end to end. |
| **CP4** | Coding, advanced proctoring, notifications and webhooks. |
| **CP5 + CP6 (automated)** | SSO/SCIM, ATS and public API, analytics, administration; the golden path and every CI gate green. |

- **Daily report.** The main session posts one: what merged, what's red, and which lane is at risk. A slipping lane drops to its next-lowest-priority part, never its P0 work.

## 8. Testing on this PC

Everything is built and tested on this PC. GitHub's Windows CI can compile and unit-test the desktop, but can't run it against real hardware.

**Setting up once:**
1. Keep this PC awake, Docker Desktop running, and Claude Code open in the repo.
2. Fix `GEMINI_API_KEY` in the local `.env`.

**Each time you test** (in Git Bash, from `D:/Deva/Hirevion`):

```bash
git checkout main && git pull --ff-only     # or a part's branch, to test a PR before it merges
pnpm install && uv sync                     # after a part added dependencies
uv run hv up                                # databases, storage, mail, LiveKit (Docker)
uv run hv migrate && uv run hv seed-identity
uv run hv api                               # the API on 127.0.0.1:8000 (keep it running)
pnpm --filter @hirevion/recruitment-platform dev               # https://app.hirevion.localhost
pnpm --filter @hirevion/ai-interviewer-desktop tauri dev       # the candidate app
```

- **The AI:** set `HV_AI_PROFILE=mock` in `.env` for predictable runs, or `dev` to use Gemini and Deepgram.
- **Email:** invitations, codes and resets arrive in Mailpit at http://127.0.0.1:8025.
- **Sign-in:** the seeded recruiter is `recruiter@acme.example.test`, and the password is `HV_SEED_PASSWORD` in `.env`.

**What to test, at each checkpoint** (each step builds on the one before):

| Checkpoint | Try this here |
|---|---|
| CP2 | Create a job, upload resumes and shortlist. Build a template and invite a candidate (A1). Set the candidate's password from the Mailpit email (A3). Sign in to the desktop app, run the system check with your webcam, and start an interview: talk to the AI voice, finish, and watch the upload drain. |
| CP3 | Pair your phone as the third eye (same Wi-Fi). Watch the interview live from the web app, with alerts as you look away or switch windows. Open the interview and proctoring reports and the review screen. |
| CP4 | A coding question (run and submit). Advanced proctoring (phone in view, a second person). Notification emails and webhook deliveries. |
| CP5/6 | SSO with the local Keycloak, administration pages, analytics, and the golden path from start to finish. |

**Reporting a problem:** add it under "Found in testing" below, on `main`, as `- [ ] <part id>: <what you did>, <what happened>, <what you expected>`. Each part's owner checks this list before starting its next part and fixes its own items first.

**After the build:** the hardware, phone, NVDA and live-vendor checks in section 1, plus the long-lead items in MASTER §17.

### Found in testing

- (none yet)

## 9. Deferrals recorded in code, so nothing is lost

- **A1 (SP-07a):** done (ADR-0020): the "Create interview" action, the candidates' Interview and Completed tabs, and interviews pinning a template version, its questions and its policy.
- **C2 (SP-09b):** done (ADR-0030): question time limits and follow-up rules are used live.
- **C6 (SP-16):** the coding question's runs, tests and grading (SP-09 asks it with the code workspace).
- **D3 (SP-13):** pairing check at `start` (until then a required third eye needs the waiver).
- **C5 (SP-14):** `Conductor.note_proctor_event` fills §34's proctor summary and the CRITICAL-event reminder; `/ws/proctoring` and `/ws/recruiter`.
- **C5 (SP-14) and D5 (SP-22):** proctoring presets become editable policies.
- **A5 (SP-17):** moving cards on the pipeline board; the remaining Candidate 360 tabs.
- **A4 (SP-18):** the notification centre's content; the scheduler.
- **D4 (SP-19):** MFA, moved from SP-02.
- **D5 (SP-22):**
  - server-backed saved views;
  - a people search beyond 2,000 users;
  - usage pages and quota settings.
