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

## In progress (unmerged worktree branches)

| Part | Branch | Exact next step |
|---|---|---|
| B3 SP-08c packaging | `sp-08c-packaging` | Commit the 15 uncommitted files; installer release build, then the tauri-driver e2e test and docs |

## Remaining, in priority order (dependency in brackets)

- **P0:** D1 rest: CI gates, code review, dashboard KPIs [none] · A3 SP-07b portal [A1] · D3 SP-13 third-eye, with Egress [D2] · A5 SP-17 reports [ready: C4, C5, D2 merged]
- **P1:** A4 SP-18 notifications/webhooks [A1] · C6 SP-16 coding server [C3] · C7 vision agent [C5, D3] · B4 desktop coding/third-eye/advanced CV [B3, C6, D3]
- **P2:** D4 SP-19 enterprise identity [SP-02] · D5 SP-22 admin/governance [A5, C5] · A6 SP-21 analytics [A5] · D6 SP-20 ATS/public API [A4, A5]
- **P3:** D7 SP-23 automated hardening [all] · B5 Windows golden path and chaos drills [B3, B4]

## Found in testing (open)

- None.

## Known blockers

- `GEMINI_API_KEY` in `.env` is invalid: the `dev` AI profile fails, so runs use `HV_AI_PROFILE=mock` until it's replaced.
- The account usage limit (resets about every 5 hours) stops subagents mid-part; resume them with SendMessage.
- Needs the product owner: hardware matrix, real phones for third-eye, NVDA pass.
- Needs a third party: code-signing certificate, Entra test tenant, ATS sandboxes, counsel review of `docs/policies/`, external pentest.
