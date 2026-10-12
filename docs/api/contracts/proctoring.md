# Contract: proctoring from the desktop

**Provider:** lane C, SP-14. **Consumer:** the desktop app (lane B: SP-11 native monitoring, SP-15a/15b on-device vision). Every call uses the interview-session token plus a DPoP proof.

The desktop reports what it observes; the server decides severity and raises alerts (master plan §6.12). Event names are §55's plus the master plan's additions.

## Open a proctor session — `POST /proctoring/session` (PRD §90)

- **Body:** `{ "interview_id": "uuid", "app_version": "1.4.0" }`.
- **`200`:**

```json
{
  "proctor_session_id": "uuid",
  "policy_version": 3,
  "level": "standard",
  "checks": ["face", "focus", "gaze", "phone", "processes", "displays"],
  "thresholds": { "FACE_ABSENT": { "warn_after_ms": 5000, "critical_after_ms": 30000 } },
  "app_rules": {
    "blocked": [ { "match": "publisher", "value": "Example Corp", "category": "remote_access" } ],
    "allowed": [ { "match": "path", "value": "C:\\Windows\\System32\\Narrator.exe" } ]
  },
  "single_display": false,
  "heartbeat_seconds": 5,
  "batch_max_events": 100,
  "accommodations": ["relaxed_gaze"]
}
```

- **Rule matching:** each rule matches on `name`, `path`, `publisher`, `signature`, `hash` or `window_title`. A rule never matches on the name alone without another attribute, except in an allow list.
- **Repeat calls** with the same interview return the same session (after a restart).

## Events — `POST /proctoring/events` (PRD §90)

Body:

```json
{
  "proctor_session_id": "uuid",
  "events": [
    {
      "seq": 41,
      "event": "APPLICATION_FOCUS_CHANGE",
      "source": "native",
      "started_at": "2026-10-12T05:01:02.120Z",
      "duration_ms": 3400,
      "confidence": 1.0,
      "evidence": [ { "type": "snapshot", "blob_path": "…/evidence/41-screen.jpg" } ],
      "details": { "previous_app": "AI-Interview.exe", "new_app": "chrome.exe", "window_title": "…" }
    }
  ]
}
```

- **Fields:**
  - `seq` increases by one per session with no gaps, and the desktop never reuses a number.
  - `started_at` is in server time.
  - `source` is one of `camera`, `third_eye`, `screen`, `native`, `editor`, `audio`, `interview`.
  - `details` holds the per-event metadata: §60's process fields, §62's focus fields, §63's device fields.
- **`200`:** `{ "acked_through": 41, "missing": [] }`.
- **Missing events:** the server records gaps as `TELEMETRY_GAP`, and the desktop resends what's listed in `missing`.
- **Duplicates** (a `seq` already stored) are ignored, so retries are safe.
- **Event names:**
  - camera: `FACE_ABSENT`, `MULTIPLE_FACES`, `FACE_TOO_FAR`, `FACE_TOO_CLOSE`, `GAZE_DEVIATION`, `CAMERA_OBSTRUCTED`, `PHONE_DETECTED`, `UNEXPECTED_PERSON_DETECTED`;
  - devices: `CAMERA_DISCONNECTED`, `MIC_DISCONNECTED`, `SCREEN_CAPTURE_STOPPED`;
  - focus and processes: `APPLICATION_FOCUS_CHANGE`, `WINDOW_MINIMIZED`, `BLOCKED_PROCESS_DETECTED`, `EXTERNAL_DISPLAY_CHANGE`;
  - environment: `CAPTURE_EXCLUDED_WINDOW`, `REMOTE_SESSION_DETECTED`, `VIRTUAL_DEVICE_DETECTED`, `VM_DETECTED`, `CLIENT_INTEGRITY_WARNING`;
  - audio: `ADDITIONAL_SPEAKER_DETECTED`;
  - lifecycle: `CAMERA_RECONNECTED`, `MIC_RECONNECTED`, `SESSION_INTERRUPTED`, `SESSION_RESUMED`;
  - editor: `EDITOR_PASTE`, `EDITOR_FOCUS_CHANGE` (§48's other editor events go through the coding contract).
- **No key logging:** no event ever carries what a key typed.

## Heartbeat — `POST /proctoring/heartbeat` (PRD §90)

- **When:** every `heartbeat_seconds`.
- **Body:**

```json
{ "proctor_session_id": "uuid", "seq_high": 41, "camera": "on", "mic": "on", "screen": "capturing",
  "third_eye": "connected", "displays": 1, "cpu_percent": 31, "vision_fps": 9.5 }
```

- **`200`:** `{ "server_time": "…", "missing": [] }`.
- **Missed heartbeats:** the server raises `TELEMETRY_GAP` and the related disconnection events itself, so a client that stops sending heartbeats can't hide.

## Evidence snapshots — `POST /proctoring/evidence-uploads`

- **Body:** `{ "proctor_session_id": "uuid", "kind": "screen | camera", "seq": 41, "content_type": "image/jpeg", "bytes": 84213, "sha256": "…" }`.
- **`200`:** `{ "upload_url": "<write-only SAS, 5 minutes>", "blob_path": "…", "headers": { "x-ms-blob-type": "BlockBlob" } }`.
- **Linking:** the desktop PUTs the bytes, then references `blob_path` in the event's `evidence`.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane C; no field changes. Clarified: events and heartbeats after the interview completes answer `409 proctor-session-closed`; an unknown `event` or `source` is `422 unknown-event` (the whole batch is refused, so nothing is half-stored); a batch holds at most `batch_max_events`.
- 2026-10-11, SP-14 built (lane C), the desktop's proposals decided:
  - **(a) Accepted.** `POST /proctoring/session` always answers `acked_through` (0 for a new session): everything up to it has arrived, so a client that lost its queue continues after it.
  - **(b) Accepted.** An app rule may carry `with: [{match, value}]`; every condition must hold. A blocked `name` rule fires only through `with` (the catalogue and the database refuse a blocked name rule without one); an allowed `name` rule may stand alone. The answer lists the platform catalogue's rules, the organisation's own, and the allow rules an approved `assistive_technology` accommodation adds.
  - **(c) Accepted.** New event names `DEVICE_CHANGE` (a camera or microphone other than the one in use, §63) and `UNEXPECTED_WINDOW` (a topmost overlay, §62). Events only the server raises are not accepted from a device (`422 unknown-event`): `THIRD_EYE_DISCONNECTED`, `THIRD_EYE_RECONNECTED`, `TELEMETRY_GAP`.
  - **(d) Accepted.** `details` may hold `severity_hint` and `category` (the device suggests, the server decides: the server stores the hint as a note and takes the category from the rule at `rule_index` in the session's `app_rules.blocked`, else from `category` if the catalogue knows it); `ongoing` and `continued` on focus and minimise chunks; `matched_by`, `rule_index` and `already_running` on blocked processes; and from the face module `phase` (`started`, `escalated`, `ended`), `level`, `frames`, `max_faces`, `face_height`, `mean_luma`. Events that share `event` and `started_at` and carry a `phase` are one episode, stored as one event updated in place (a later phase wins; an older one arriving late never undoes it; its severity never goes down). Keys that could carry typed or pasted text (`keys`, `keystrokes`, `text`, `clipboard`, ...) are dropped, and `details` is bounded (strings 300 characters, 8 KB in all).
  - **(e) Accepted.** A `signature` rule matches the SHA-256 (hex) of the signer certificate.
  - **(f) Accepted.** The first heartbeat should arrive as soon as the uploader starts. The server counts a heartbeat gap from the last heartbeat, or from the session's opening when there has been none, and raises `TELEMETRY_GAP` after `heartbeat_seconds` x 4 (20 s) of silence.
  - **`missing` is a flat list of sequence numbers**, lowest first, at most 500, in the events and the heartbeat answers (the heartbeat adds what `seq_high` says the device made and the server hasn't got). Numbers still missing 30 s after they were first noticed are recorded once as a server `TELEMETRY_GAP` (retries and batches that arrive out of order fill them sooner and raise nothing). `started_at` must carry a time zone (`422` otherwise).
  - **Bounds:** a `seq` below 1 or more than 100 000 ahead of the highest received is `422 seq-out-of-range`; a batch over `batch_max_events` is `422 batch-too-large`.
  - **After the interview ends**, events are still accepted for 10 minutes so the desktop can drain its queue; heartbeats and evidence slots for a closed session are `409 proctor-session-closed` at once, and so is everything after the 10 minutes.
  - **Level `off`:** the session opens with no checks; events are acknowledged and not stored.
  - **Snapshots on request.** When a CRITICAL event is raised the server asks for a screen picture (and a camera one where the camera matters). The heartbeat answer gains `snapshot_requests: [{request_id, event_id, kind: "screen | camera", requested_at}]`; a request expires after two minutes. The desktop answers with `POST /proctoring/evidence-uploads` carrying `request_id` (the `kind` must match and `seq` is not needed), takes the same write-only URL as for any snapshot, and PUTs the picture; the blob is already linked to the event. Asking again with the same hash gives the same blob; a different hash is `409 evidence-locked`; an unknown or foreign `request_id` is `404 snapshot-request-not-found`. A snapshot the device takes by itself still needs `seq` and is named in the event's `evidence`.
