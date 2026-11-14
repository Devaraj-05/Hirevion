# Hirevion — status

Git is the source of truth; update this file in the PR that merges a part. Part ids are from `PENDING_TASKS.md` section 6.

## Done (merged to `main`)

| Part | What | PR / ADR |
|---|---|---|
| SP-00–SP-03 | Foundations and spikes, backend core, identity and access, web shell | before PR #1 / ADR-0001–0014 |
| SP-04 | Jobs, JD and resume pipelines | #1, #2 / ADR-0015 |
| SP-05 | Screening and ranking | #3 / ADR-0016 |
| SP-06 | Interview configuration | #4 / ADR-0017 |
| A0, C0, D0 | Contract reviews | #7 |
| A1 SP-07a | Interviews, invitations, lifecycle, scheduler | #7 / ADR-0020 |
| A2 SP-07c | Desktop candidate auth, DPoP, releases | #7 / ADR-0021 |
| C1–C3 SP-09 | AI interview engine, agent, simulator | #7 / ADR-0030 |
| D1 (part) | Policy drafts, SP-01–06 threat models, `hv trace --check` | #7 |
| D1 rest | CI gates (coverage at 85% on `hirevion_core` and a web floor, Bandit, Semgrep, osv-scanner, licences, Trivy and Syft SBOM; all through `scripts/gates.sh`), the SP-04a to SP-06 code review with its fixes, the ten PRD section 10 dashboard figures under seven filters | #19 |
| B1 SP-08a | Desktop sign-in, device keys, system check | #6 / ADR-0018 |
| B2 | SP-11 monitoring, SP-12 client recording, SP-15a desktop vision | #9 |
| B3 (part) SP-08b | Briefing, consent, interview path, services, upload drain | #9 |
| D2 SP-12 server | Segment upload and acknowledgement, assembly, continuity, audited playback | #11 |
| C4 SP-10 | Evaluation on eight dimensions with evidence, pinned re-runs, eval gate, reviewer calibration | #12 / ADR-0031 |
| C5 SP-14 | Proctoring pipeline, severity rules, evidence and snapshots, server-observed state, live dashboard, event review | #13 / ADR-0032 |
| A3 SP-07b | Candidate portal: own cookies and CSRF, invitation link, sign-in and resets, interviews with countdowns, download, §83 notices, report placeholder, requests acted on at `/candidates/requests` | #15 / ADR-0022 |
| B3 SP-08c | Per-user installer (x64), signed updater, crash reports, desktop e2e; open items moved to B4/B5 | #14 / ADR-0019 |
| A5 SP-17 | Reports, review and Candidate 360: five reports as a web view and a stored PDF, the review workspace (11 actions, synchronised recordings), score changes with reasons, Hiring Manager input, the nine hiring statuses and the human decision, the candidate-visible report with a recruiter's release, 13 Candidate 360 tabs with one timeline, the pending-review queue, pipeline moves; CP3 golden path e2e | #18 / ADR-0023 |
| C6 SP-16 | Coding answers without execution (product-owner decision, 2026-10-23): the AI asks, the candidate types in a text console and submits once (the time limit keeps the last draft), every submission stored; the console's integrity events (lengths only, no keystrokes) as signals; the AI reviews the code after the interview inside the evaluation (seven criteria, evidence verified against the code's lines, pinned prompt and rubric, a gated coding set); the coding report, Candidate 360 Coding tab and review panel; contract `coding.md` for B4 | pending / ADR-0033 |
| D3 SP-13 | Third eye: single-use QR pairing, the phone page (permission guidance, placement, 720p/15 fps rear camera, Wake Lock, pause on lock, reconnect), LiveKit-observed status into proctoring, the `start` gate; Egress of the conversation audio and the third-eye video into playback | #17 / ADR-0040 |

## In progress (unmerged worktree branches)

| Part | Branch | Exact next step |
|---|---|---|

## Remaining, in priority order (dependency in brackets)

- **P1:** C7 vision agent [C5, D3] · B4 desktop coding console (notepad-style, no Run)/third-eye/advanced CV [B3, C6, D3]
- **P2:** D4 SP-19 enterprise identity [SP-02] · D5 SP-22 admin/governance [A5, C5] · A6 SP-21 analytics [A5] · D6 SP-20 ATS/public API [A5]
- **P3:** D7 SP-23 automated hardening [all] · B5 Windows golden path and chaos drills [B3, B4]

## Skipped by product-owner decision

- A4 SP-18 notifications and webhooks (2026-10-25): no notification centre, preferences or outbound webhooks; the existing emails stay (MASTER §6.14).

## Found in testing (open)

- [ ] D1: `livekit-local-inference` ships under the LiveKit Model License, which the licence gate accepts only as a recorded exception (`hirevion_devcli/licenses.py`). Have counsel read its terms before a commercial release.
- [ ] D1: a hiring manager of a job outside their team sees the job and its candidates (`job_scope_clause`) but not its interviews (`interviews_statement` has no assigned-job reach), so the dashboard's interview figures, the Interviews page and the reports leave those out. Decide whether the "assigned jobs" rule extends to interviews and reports (A1/A5 access code).
- [ ] D1 review, out of scope (A1/A5 code): the reviewers dialog lists disabled users; the interview page has no time-zone label; the evaluation re-run button can stick; the candidate page doesn't refresh after an action taken elsewhere; the assign dialog shows raw window codes.
- [ ] B3: the desktop e2e (`scripts/ci-local.sh desktop-e2e`) has stalled at the system check four times: once with "Camera: not available" right after the desktop job (October), and three times on 2026-11-14 on both this branch and `main`, right after WebView2 updated to 157 while the Docker stack was starting. An instrumented run then passed, and the unchanged test passed twice in about 10 s. Hypothesis: the first launches after a WebView2 update, or a saturated PC, push the camera/microphone checks past the test's waits. If it recurs on a quiet PC, have `e2e/desktop.e2e.mjs` log the page text and a screenshot each second from "Run the check" to consent before changing anything.
- [ ] D3: not yet tried on real phones (iOS Safari 16.4+, Android Chrome; the owner's check, runbook "Third eye") or with the real Egress container (its image is about 1 GB; tests used the adapter's fake). Run both before CP3.
- [ ] A5/D2: ffmpeg isn't installed on this PC, so recordings stay assembly-pending and the review player's sync is tested only with pure functions and jsdom. Install ffmpeg (see the runbook's "Recordings") and play a simulator interview's recordings end to end before CP3.
- [ ] B2/SP-11: `event-queue`'s end-to-end test (a blocked process is queued within 2 s) failed once in a full local CI run on a heavily loaded PC (65 s run time; it took 14 s alone and passed). The 2 s is the product requirement, so it stays; watch whether detection really slows under load.
- [ ] D1: GHSA-xcq7-p3pf-p88h and GHSA-mf5v-w3w3-f6cg (OpenTelemetry `tracestate` and `traceparent` parsing, medium) are accepted until 2026-12-31: the API drops either header over 512 characters (`TraceStateGuard`). The real fix, opentelemetry-api 1.45.2, needs livekit-agents 1.8.8 and so the OpenAI SDK 3; do that upgrade (AI layer and interview agent) before the expiry.

- [ ] Desktop: RUSTSEC-2026-0387 (crypto-bigint 0.5 timing, via p256 0.13 in `hv-security`) is accepted until 2027-02-28: The Windows app signs DPoP proofs only through the Windows key store (NCrypt: the TPM or the Microsoft software KSP); it never falls back to a software key. p256 only verifies public signatures there, and signs only in non-Windows builds (not shipped) and tests. Upgrade `hv-security` to p256 0.14 before the expiry.

## Known blockers

- `GEMINI_API_KEY` in `.env` is invalid: the `dev` AI profile fails, so runs use `HV_AI_PROFILE=mock` until it's replaced.
- The account usage limit (resets about every 5 hours) stops subagents mid-part; resume them with SendMessage.
- Needs the product owner: hardware matrix, real phones for third-eye, NVDA pass.
- Needs a third party: code-signing certificate, Entra test tenant, ATS sandboxes, counsel review of `docs/policies/`, external pentest.
