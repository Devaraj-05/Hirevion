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
| B1 SP-08a | Desktop sign-in, device keys, system check | #6 / ADR-0018 |
| B2 | SP-11 monitoring, SP-12 client recording, SP-15a desktop vision | #9 |
| B3 (part) SP-08b | Briefing, consent, interview path, services, upload drain | #9 |
| D2 SP-12 server | Segment upload and acknowledgement, assembly, continuity, audited playback | #11 |
| C4 SP-10 | Evaluation on eight dimensions with evidence, pinned re-runs, eval gate, reviewer calibration | #12 / ADR-0031 |
| C5 SP-14 | Proctoring pipeline, severity rules, evidence and snapshots, server-observed state, live dashboard, event review | #13 / ADR-0032 |
| A3 SP-07b | Candidate portal: own cookies and CSRF, invitation link, sign-in and resets, interviews with countdowns, download, §83 notices, report placeholder, requests acted on at `/candidates/requests` | #15 / ADR-0022 |
| B3 SP-08c | Per-user installer (x64), signed updater, crash reports, desktop e2e; open items moved to B4/B5 | #14 / ADR-0019 |
| A5 SP-17 | Reports, review and Candidate 360: five reports as a web view and a stored PDF, the review workspace (11 actions, synchronised recordings), score changes with reasons, Hiring Manager input, the nine hiring statuses and the human decision, the candidate-visible report with a recruiter's release, 13 Candidate 360 tabs with one timeline, the pending-review queue, pipeline moves; CP3 golden path e2e | #18 / ADR-0023 |
| D3 SP-13 | Third eye: single-use QR pairing, the phone page (permission guidance, placement, 720p/15 fps rear camera, Wake Lock, pause on lock, reconnect), LiveKit-observed status into proctoring, the `start` gate; Egress of the conversation audio and the third-eye video into playback | #17 / ADR-0040 |

## In progress (unmerged worktree branches)

| Part | Branch | Exact next step |
|---|---|---|

## Remaining, in priority order (dependency in brackets)

- **P0:** D1 rest: CI gates, code review, dashboard KPIs [none]
- **P1:** A4 SP-18 notifications/webhooks [A1] · C6 SP-16 coding server [C3] · C7 vision agent [C5, D3] · B4 desktop coding/third-eye/advanced CV [B3, C6, D3]
- **P2:** D4 SP-19 enterprise identity [SP-02] · D5 SP-22 admin/governance [A5, C5] · A6 SP-21 analytics [A5] · D6 SP-20 ATS/public API [A4, A5]
- **P3:** D7 SP-23 automated hardening [all] · B5 Windows golden path and chaos drills [B3, B4]

## Found in testing (open)

- [ ] B3: the desktop e2e once failed at the system check with "Camera: not available" when run right after the desktop job in `scripts/ci-local.sh`; it passed alone and on the next full run. Watch for it; if it recurs, find what holds the camera.
- [ ] D3: not yet tried on real phones (iOS Safari 16.4+, Android Chrome; the owner's check, runbook "Third eye") or with the real Egress container (its image is about 1 GB; tests used the adapter's fake). Run both before CP3.
- [ ] A5/D2: ffmpeg isn't installed on this PC, so recordings stay assembly-pending and the review player's sync is tested only with pure functions and jsdom. Install ffmpeg (see the runbook's "Recordings") and play a simulator interview's recordings end to end before CP3.

## Known blockers

- `GEMINI_API_KEY` in `.env` is invalid: the `dev` AI profile fails, so runs use `HV_AI_PROFILE=mock` until it's replaced.
- The account usage limit (resets about every 5 hours) stops subagents mid-part; resume them with SendMessage.
- Needs the product owner: hardware matrix, real phones for third-eye, NVDA pass.
- Needs a third party: code-signing certificate, Entra test tenant, ATS sandboxes, counsel review of `docs/policies/`, external pentest.
