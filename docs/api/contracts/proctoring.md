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
