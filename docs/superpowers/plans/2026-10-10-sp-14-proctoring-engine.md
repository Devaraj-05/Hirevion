# SP-14 Proctoring Engine and Live Monitoring Implementation Plan

**Goal:** PRD §54, §55, §64 to §67 and §90 as the master plan's §6.12 describes them, implementing `docs/api/contracts/proctoring.md`. Lane C's part C5: the server side of proctoring and the recruiter's live view. The desktop's monitoring (SP-11) and on-device vision (SP-15a) are built against the contract already.

**Architecture:**
- **`hirevion_core.proctoring`** holds the engine, one module per pipeline stage (§54):
  - `catalogue`: the event names, their sources and families, and the details cleaning (no key logging).
  - `normaliser`: a client event becomes a stored shape (clamped times and confidence, cleaned details, evidence references, the app rule behind a blocked process).
  - `aggregator`: temporal aggregation. Events that share `event` and `started_at` and carry a `phase` are one episode, updated in place. Sequence tracking keeps `acked_through` and the gap ranges.
  - `rules`: the rule engine. Pure functions from the pinned policy and the recent history to a severity with its reasons: duration tiers, the fixed table, categories, single-display, repetition escalation, and "never CRITICAL alone" for gaze.
  - `policy`: builds the session's pinned policy from the interview's snapshot (SP-07a), the platform catalogue (`app_categories`, `app_rules`), approved accommodations and optional overrides. It also shapes the answer of `POST /proctoring/session`.
  - `evidence`: the evidence manager. Write-only upload slots, linking of uploaded snapshots to events, and server-added references (process metadata, transcript and recording windows).
  - `observed`: server-observed state. Channels (camera, microphone, screen, third eye, heartbeat) get votes from heartbeats, LiveKit webhooks and upload continuity. A watcher turns a channel that stays down into `*_DISCONNECTED`, `SCREEN_CAPTURE_STOPPED`, `THIRD_EYE_DISCONNECTED` or `TELEMETRY_GAP`, and raises their severity as they last.
  - `service`: `ProctorEngine` ties the stages to the database, to the realtime stream and to the interview (the Conductor's proctor summary and candidate nudges).
  - `review`: confirm, mark as a false positive or not relevant, always with a reason and an audit entry. Nothing is deleted.
- **Tables (migration 0016):** `proctor_sessions` (the pinned policy, sequence tracking, heartbeat and observed state), `proctor_events`, `proctor_evidence`, `proctor_event_reviews`, and the platform catalogue `app_categories` and `app_rules` with seed data. `scheduler_proctor_sessions_due` lists the sessions the watcher must look at, as the interview scheduler does.
- **Realtime:** alerts go to the interview's capped Valkey stream `hv:rt:interview:{id}` as `PROCTOR_EVENT`, `PROCTOR_STATUS` and `PROCTOR_REVIEW`. `/ws/proctoring/{id}` follows it for `reports.proctoring.view` holders, replaying from `?after=`. `/ws/interviews/{id}` hides these types from anyone without that permission.
- **API:**
  - Desktop (interview-session token plus DPoP): `POST /proctoring/session`, `/events`, `/heartbeat`, `/evidence-uploads`.
  - Recruiter: `GET /proctoring/{interview_id}` (the report data), `/live` (the dashboard snapshot), `/evidence`, `POST /proctoring/{interview_id}/events/{event_id}/review` and `/observe` (a hidden, subscribe-only LiveKit token).
  - LiveKit's webhook also feeds track and participant changes to the engine.
- **Consumers:** `recording.gap` (SP-12's outbox topic) and `interview.completed` and `interview.abandoned` (which close the proctor session).
- **Web:** a live monitoring panel on the interview page. A pure reducer keeps the state (devices, connection health, recent events, transcript tail) and merges the snapshot with the websocket's events by id. The socket reconnects from the last event id and refetches the snapshot.

**Decisions** (the ADR is 0032): no new permission (reviewing needs `interviews.manage` as well as `reports.proctoring.view`); `proctor_events` is not partitioned (the idempotency key `(session, seq)` and in-place episode updates need unique indexes a partition key would break); the server decides severity and keeps the device's `severity_hint` only as a note.

## Tasks

1. **Plan, contract decisions** (a) to (f) under "Changes" in `proctoring.md`.
2. **Schema (tests first):** migration 0016, models, the tenant-isolation harness, the catalogue's invariants (no blocked name-only rule).
3. **Pure engine (tests first):** catalogue, normaliser, aggregator, rules (every row of the §6.12 table, escalation, gaze), policy builder.
4. **Ingestion (tests first):** open session, batches (idempotent, `missing`, gaps, `409`, `422`), heartbeats, evidence.
5. **Server-observed state:** votes, the watcher, LiveKit tracks, `recording.gap`, closing on completion.
6. **Recruiter side:** report, live snapshot, evidence, review with audit, the websocket and its replay, the observer token, the latency test.
7. **Nudges:** configurable, rate limited, pushed to the agent's `hv.state`, and the Conductor's summary.
8. **Web:** reducer and panel with Vitest.
9. **Docs:** matrix rows, OpenAPI and codegen, runbook, Appendix A, threat model, ADR, `PENDING_TASKS.md`.

**Exit criteria:** events reach the dashboard in under 1 s (p95, measured in a test over the real stream); a reconnecting dashboard receives the alerts it missed; dismissed events are audited and still in the report.
