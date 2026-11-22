# C8-9 One attempt, one device, a secured slot — implementation plan

> For agentic workers: use superpowers:executing-plans; tests first (superpowers:test-driven-development). Checkbox steps.

**Goal:** an interview is taken once, on one laptop, inside its window; one reconnect within 2 minutes after a crash or network drop; then it ends as "Ended early" and is evaluated. The server enforces it; the app offers no way back.

**Owner's decision (2026-11-22):** End Interview or closing the window ends it for good. After a crash or a lost connection: one reconnect, within 2 minutes, from the same laptop, the clock running, flagged to the recruiter. After that the interview ends and what was answered is evaluated.

**Architecture:**
- One pure function decides a candidate's attempt (`interview_session/attempts.py`). The candidate list, the session-token route, the preparation routes and `Conductor.start` all ask it.
- The device is the session token's DPoP key thumbprint (`claims.jkt`), stored at the first start.
- New interviews get a strict `resume` policy. Old snapshots keep theirs (PRD §80): `resume_policy()` defaults are unchanged and `same_device` defaults to false.

**Tech:** FastAPI + SQLAlchemy (backend/core, backend/api), Alembic, React/Tauri desktop (webview + Rust stub), Next.js recruiter page.

## Global constraints

- MASTER §13: RFC 9457 problems, UUIDv7, RLS, audit, TDD, ≥ 85% coverage on `hirevion_core`, the OpenAPI client regenerated, Conventional Commits.
- Author `Devaraj-05 <padma.devaraj1800@gmail.com>`; no attribution trailers; never `--no-verify`. Never read `.env`.
- New interviews' policy: `resume = {grace_seconds: 120, max_interruptions: 1, pause_timer: false, same_device: true}`.

## Codes

| Situation | HTTP | code |
|---|---|---|
| completed / evaluating / evaluated / abandoned | 409 | `interview-already-taken` |
| interrupted past the window or over the count | 409 | `resume-limit-reached` (existing) |
| a resume from another device | 409 | `interview-other-device` |
| still connected in the room (second app) | 409 | `interview-in-use` |
| not opened / expired / cancelled | as today (`interview-not-open` 409, `interview-expired` 410) |

---

### Task 1: the attempt function and the strict policy

**Files:**
- Create: `backend/core/src/hirevion_core/interview_session/attempts.py`
- Modify: `backend/core/src/hirevion_core/interview_session/briefing.py` (`ResumePolicy.same_device`), `backend/core/src/hirevion_core/interviews/assignment.py` (`RESUME_POLICY`)
- Test: `backend/core/tests/test_attempts.py`, update `backend/core/tests/db/test_interview_assignment.py`

- [ ] **Failing tests:** `attempt_of(interview, row, jkt=…, now=…)` returns:
  - `available` for invited inside the window, `not_open` before it, `expired` after it;
  - `used` for completed/evaluating/evaluated/abandoned/cancelled;
  - `reconnect` (no deadline) for in_progress on the same device;
  - `reconnect` with `reconnect_until = interrupted_at + grace` while interrupted inside the window and under the count;
  - `used` once the window or the count has passed;
  - `elsewhere` for another device when `same_device` is on;
  - an old snapshot (no `same_device`) never says `elsewhere`.
  
  `resume_policy()` reads `same_device` (default false). `policy_snapshot()` writes the strict policy.
- [ ] Implement, run `uv run pytest -x -q backend/core/tests/test_attempts.py backend/core/tests/db/test_interview_assignment.py`.

### Task 2: the conductor — device binding, one reconnect, `left_early`

**Files:**
- Modify: `backend/core/src/hirevion_core/interview_session/conductor.py` (`start`, `_check_startable`, `_first_start`, `interrupt`, new `end_left_early`, shared completion helper), `backend/core/src/hirevion_core/models/interview_session.py` (`device_jkt`), new migration `backend/migrations/versions/00xx_interview_session_device.py`
- Test: `backend/core/tests/db/test_conductor.py` (new cases)

- [ ] **Failing tests:**
  - the first start stores `device_jkt`;
  - a resume from another `jkt` → `interview-other-device`;
  - a resume with no check/consent ids uses the stored ones;
  - with the strict policy the clock isn't paused by `interrupt`;
  - the second drop (`interruptions > 1`) completes the interview with reason `left_early` and queues evaluation;
  - an `in_progress` start on the same device counts an interruption, and is refused with `interview-in-use` while the media says the candidate is present;
  - a completed interview → `interview-already-taken`;
  - old-policy behaviour is unchanged.
- [ ] Implement. `_complete`'s body becomes a module helper reused by `end_left_early(session, interview, now)` (transition to `completed`, reason `left_early`, checkpoint `ended_reason`, `ended_at`, application stage, transcript row).

### Task 3: the scheduler

**Files:** `backend/core/src/hirevion_core/interviews/scheduler.py` (`_handle`, `SchedulerReport.ended_early`); test `backend/core/tests/db/test_interview_scheduler.py` (or the existing scheduler test file).

- [ ] **Failing tests:** strict policy past the grace → `completed` with reason `left_early`, evaluation queued, not back to the shortlist; old policy → `abandoned` as today.
- [ ] Implement.

### Task 4: the API

**Files:**
- `backend/api/src/hirevion_api/interview_session/routes.py` and `schemas.py`: `StartBody` ids optional; pass `principal.claims.jkt`; `_load_open` on briefing, system-checks, consents, accommodations;
- `backend/core/src/hirevion_core/candidate_access/service.py` and `backend/api/src/hirevion_api/candidate_auth/schemas.py`: the list's `attempt` and `reconnect_until`; the session token refuses another device and a used reconnect;
- the contracts `docs/api/contracts/interview-session.md` and `candidate-auth.md`;
- the regenerated OpenAPI and `packages/api-client/src/schema.d.ts`.

Tests: `backend/api/tests/test_interview_session_api.py`, `backend/api/tests/test_candidate_auth_api.py`.

- [ ] **Failing tests:** each refusing route and its code; the list carries `attempt`; a used reconnect drops out of the list; a resume start without ids works.
- [ ] Implement, `uv run hv openapi --check` (update), `pnpm --filter @hirevion/api-codegen generate`.

### Task 5: the recruiter page

**Files:** `recruitment-platform/src/interviews/interview-page.tsx` (Policy card "Attempts" row; the completed event's reason labelled), `recruitment-platform/messages/*.json` (or the app's message files); its tests.

- [ ] **Failing test**, then implement.

### Task 6: the desktop

**Files:**
- `ai-interviewer-desktop/src/flow/flow.ts` (no `back` from completed; a `reconnect` screen);
- `src/screens/interview.tsx` (`CompletedScreen` → Close app; `onCloseRequested` → the End dialog);
- `src/screens/interviews.tsx` (re-fetch with `commands.profile()`; buttons from `attempt`);
- new `src/screens/reconnect.tsx` (close-apps check, then `start` without ids);
- `src/native/commands.ts` (types, `has_saved_session`), the Rust command for the saved session;
- `src-tauri/capabilities/default.json` (`core:window:allow-destroy`);
- the Rust stub (`attempt`, an interrupted interview);
- i18n `en-US`/`en-IN`;
- `e2e/desktop.e2e.mjs`.

Tests: `src/flow/flow.test.ts`, a new `src/interview/attempt.test.ts`, the Rust stub tests, the e2e.

- [ ] Failing tests, then implement, then run `pnpm vitest run <files>`, `cargo test -q`, `pnpm --filter @hirevion/ai-interviewer-desktop e2e`.

### Task 7: docs, review, land

- [ ] ADR-0049; STATUS and PENDING_TASKS (C8 item 9); `bash scripts/ci-local.sh python contract js e2e desktop desktop-e2e semgrep`.
- [ ] Live: finish, then try to re-enter (app and API); kill the app mid-interview and rejoin within 2 minutes; a second drop ends it as "Ended early".
- [ ] `/code-review`, fixes, push, fast-forward `main`, stop.
