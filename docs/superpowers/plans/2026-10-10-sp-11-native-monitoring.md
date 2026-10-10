# SP-11 Native Windows monitoring — plan

- **Lane:** B (the local Windows PC).
- **Master plan:** §14 SP-11, §6.12 "Native Windows monitoring" and the severity table.
- **PRD:** §60–63 (process metadata, prohibited-application policy, focus, displays and devices), §64 (severity is the server's), §67 (event schema).
- **Contract:** `docs/api/contracts/proctoring.md` (`/proctoring/session`, `/proctoring/events`, `/proctoring/heartbeat`).

**Goal:** two crates the app wires in during SP-08b:

1. `hv-monitor` observes the machine and emits typed `Observation`s;
2. `hv-event-queue` turns them into contract events (policy matcher and on-device temporal rules), stores them durably with a sequence number, and uploads them with heartbeats.

## Decisions

- **Observe, don't judge.** The device reports what it sees; the server decides severity (contract). The matcher only adds a `severity_hint` and `category` in `details`.
- **No keystroke code at all.** No keyboard hooks, no `GetAsyncKeyState`, no raw input. A test scans both crates' sources and fails on any keyboard-hook API. "Optional shortcut suppression" stays out of this part (see "Not in SP-11").
- **`hv-monitor` threads** (each stops through `MonitorHandle::stop`):
  - **processes**, polled every 500 ms (Toolhelp snapshot, keyed by PID + creation time so a reused PID is a new process). Each new process gets: name, PID, parent PID, full path (`QueryFullProcessImageNameW`), start time (`GetProcessTimes`), top-level window titles, SHA-256 of the executable and its Authenticode signature (`WinVerifyTrust`, embedded or catalog, no revocation network calls) with the signer subject and the SHA-256 of the signer certificate. Hash and signature are cached by path + size + modified time. Title changes are reported so window-title rules work after start.
  - **focus**, a dedicated message-loop thread with `SetWinEventHook` for `EVENT_SYSTEM_FOREGROUND` and `EVENT_SYSTEM_MINIMIZESTART/END`, out of context. It records the previous app, the new app, the time and how long the previous app held focus.
  - **environment**, polled every second: displays (count, name, size; connect, disconnect, resolution change), capture devices (Media Foundation video and audio capture sources: connect, disconnect, virtual devices from a data-driven name list), visible top-level windows of other processes with `GetWindowDisplayAffinity` ≠ `WDA_NONE`, topmost layered overlays, remote session (`SM_REMOTESESSION`, `SM_REMOTECONTROL`), and a debugger attaching.
  - **once at start:** the hypervisor bit and vendor from CPUID (`VM_DETECTED`, evidence only), and integrity findings handed in by the app (`WEBVIEW2_*` variables, debugger at launch).
  - Diffing (processes, displays, devices, windows) is pure code tested with fakes; the Win32 calls are thin.
  - **Time:** every observation is stamped by a clock the app supplies (`ApiClient::server_now_ms`), so events carry server time.
- **`hv-event-queue`:**
  - **Typed names.** `EventName` and `Source` enums hold exactly the contract's names; nothing else can be queued, because an unknown name makes the server refuse the whole batch (`422 unknown-event`).
  - **Policy matcher** (§61): rules match `name`, `path`, `publisher`, `signature` (SHA-256 of the signer certificate), `hash` or `window_title`. A blocked rule on the name alone never fires; it needs a `with` condition (proposed contract addition). Allow rules may use the name alone, but an allow only overrides a block matched by an equally weak or weaker attribute (strength: hash > signature > publisher > path > window title > name), so renaming a blocked binary to an allowed name doesn't help. Publisher and signature only match a valid signature. A blocked rule with a category hints CRITICAL, without one WARNING. Each process and rule is reported once.
  - **Device rules** (thresholds from the session policy's `thresholds`, defaults from the §6.12 table): `APPLICATION_FOCUS_CHANGE` and `WINDOW_MINIMIZED` only once the interview app has been away or minimised for more than 3 s, with the duration; a long period is split into back-to-back chunks (10 s by default) so the server hears about it while it lasts. Camera and microphone disconnects and reconnects; display changes; capture-excluded windows; remote session; virtual devices; VM; integrity.
  - **Durable queue:** one directory per proctor session holding `events.jsonl` (append-only, fsynced) and `state.json` (`acked_through`, written by rename). `seq` is assigned at append, starts at 1, never reused across restarts (a torn last line is dropped before the next append); the server's `acked_through`, when the session answer carries it, raises the floor.
  - **Uploader** (Tokio): batches of at most `batch_max_events` in `seq` order; exponential backoff with jitter capped at 30 s, honouring `Retry-After`; resends what the server lists as `missing` (events and heartbeat answers); heartbeat every `heartbeat_seconds` with `seq_high` and device status from a callback. `409 proctor-session-closed` stops both loops for good.
  - **Signed:** every request carries a DPoP proof from the device key (the contract's mechanism). Binding the body into the proof is a proposed contract change, not built here.
- **Dependencies:** `windows` (workspace, plus `Win32_Security_WinTrust`, `Win32_Security_Cryptography_Catalog` on the crate), `sha2`, `serde`, `serde_json`, `tokio`, `fastrand`; `wiremock` for tests. All MIT/Apache-2.0.

## Tasks

1. `hv-monitor` model and pure diffing: processes, displays, devices, virtual-device names, windows. Tests first with fakes.
2. `hv-monitor` native: process snapshot, hash cache, signatures; windows scan with affinity; displays; Media Foundation devices; focus hook thread; remote session, CPUID, debugger; `Monitor::start` / `stop`. Tests: a helper window with `WDA_EXCLUDEFROMCAPTURE` is reported within 2 s; a copy of a signed system binary under a new name is reported with its hash and signer within 2 s; the keystroke-code scan.
3. `hv-event-queue` model, RFC 3339 server-time stamps, policy matcher, device rules. Tests: blocked by hash, by signature, by publisher; renamed binary still blocked; name-only block ignored; allow precedence; focus away > 3 s with duration; display change.
4. Durable queue: restart keeps `seq`, torn tail, `acked_through`. Uploader against `wiremock`: batching, `missing` resend, backoff on 503, `409` stop, heartbeat body.
5. End to end: the real monitor feeding the rules and the queue raises `BLOCKED_PROCESS_DETECTED` for a renamed blocked binary and `CAPTURE_EXCLUDED_WINDOW` within 2 s.

## Not in SP-11 (owned elsewhere)

- Wiring into the app (threads, Tauri state, commands): SP-08b, from the integration note in the report.
- Fullscreen and app-exit tracking of the interview window: Tauri window events in SP-08b, appended by the app to the same queue as `EventDraft`s.
- Optional shortcut suppression: SP-08b, with the kiosk window settings, never by reading keys.
- Evidence snapshots (`/proctoring/evidence-uploads`): with SP-12's capture pipeline.

## Proposed contract changes (for lane C)

- `/proctoring/session` answer: `acked_through`, so a client that lost its local queue doesn't restart at `seq` 1.
- App rules: an optional `with: [{match, value}]` on a rule, the only way a blocked name rule can fire.
- New event names `DEVICE_CHANGE` (a camera or microphone that isn't the active one) and `UNEXPECTED_WINDOW` (§62: topmost overlays). Until they're accepted the queue never sends them.
- Body binding: an extra DPoP claim with the SHA-256 of the request body.
