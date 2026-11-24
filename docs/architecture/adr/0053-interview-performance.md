# ADR-0053: Interview performance: no transaction across AI calls, live audio first, no per-frame re-blur

- **Status:** Accepted
- **Date:** 2026-11-25
- **Sub-project:** C8-12 follow-up (interview plan worker, interviewer agent, candidate desktop app)

## Context

The product owner's run of 2026-11-24 on the new screen: "the interview is getting full lag very slow, and the AI voice is full stuck and flickering". What the logs and measurements showed:

- **The interviewer agent was starved of CPU.**
  - Its voice detector fell up to 19 s behind real time ("VAD inference is slower than realtime").
  - Its speech was produced more slowly than it plays ("slow audio generation", heard as a stuck, flickering voice).
  - The greeting took 54 s to finish.
  - The vision agent recorded the machine at full load (`load 1.0`). A later 20 s sample of the same PC: 720% of 800% CPU, with the browser at 238%.
- **Starting right after scheduling waited a minute.** The question-plan worker (ADR-0050) held one database transaction through its AI calls. Inserting the plan row took a foreign-key share lock on the interview, so start's `SELECT … FOR UPDATE` waited (observed in `pg_stat_activity`: about 60 s, "idle in transaction").
- **The new screen was expensive** (headless Chromium, whole browser, % of one core).
  - The glass blur on the cards (`backdrop-filter`) was re-rendered on every camera frame: 88% with the orb still, against 9% without the blur.
  - The orb wrote its level as a CSS variable on the whole card, so each frame restyled the transcript too: 117% while speaking.

## Decision

- **The plan worker never holds a transaction while the AI writes.** `handle_plan_event` runs in three steps:
  1. A short transaction reads the inputs and claims the plan (a pending row).
  2. The AI calls run with no transaction open.
  3. A short transaction stores the result.
  
  Safeguards:
  - A fresh claim (10 minutes, the queue's redelivery time) makes a duplicate event stop.
  - A stale claim (the writer died) is taken over, and `ensure_plan` asks again.
  - Storing re-checks that the interview is still live.
  - `write_plan(session, …)` keeps the one-session form for callers that hold a session.
- **Live audio first.** The interviewer agent raises its own scheduling priority in `main()` and in each job's prewarm:
  - **Windows:** the "above normal" class. The process handle's type is declared, because an undeclared 64-bit handle made Windows refuse the call.
  - **Elsewhere:** an absolute nice of −5, which needs CAP_SYS_NICE and is skipped without it.
- **The screen paints once and then only composites.**
  - **Glass:** no `backdrop-filter` on the interview's cards or bar. They sit on a still gradient, so the blur bought nothing visible.
  - **Orb loop:** it sets five transforms directly (the sphere, three rings and the waveform strip as one piece) through `scales(level)`, and only when the value changes.
  - **Layers:** each of those five has its own compositor layer (`will-change: transform`).
- **Measuring tools:**
  - `pnpm e2e -- --probe` (`e2e/cpu-probe.mjs`) measures the app's CPU on the interview screen.
  - The gallery's `?audio=1` drives the orb with a synthetic voice.

## Consequences

Measured on the owner's PC (8 logical CPUs). The voice benchmark used 4 turns, so its latency spread is wide.

| Measure | Before | After |
|---|---|---|
| Start right after scheduling | timed out after 30 s, blocked about 60 s | not blocked (lock test; the benchmark completes) |
| Saturated PC, agent at normal priority vs above normal: slow-TTS flushes | 4 | 0 |
| Same: event-loop blocks | 26 | 12 |
| Screen, orb still | 88% | 9–11% |
| Screen, interviewer speaking | 117% | 59–71% |

Not changed here:
- **Debug build:** `tauri dev` runs an unoptimised Rust build. Use `tauri dev --release` to judge speed.
- **Shared PC:** a development PC also runs Docker, the API, both agents and a browser. In production the agents run on their own servers.
- **Valkey:** the API's "Valkey is unavailable" rate-limit warnings come from pooled connections the server had closed. They're harmless here and still open.
