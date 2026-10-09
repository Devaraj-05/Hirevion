# Contract: the interview session

**Provider:** lane C, SP-09; the system-check and consent storage can land with SP-09a. **Consumer:** the desktop app (lane B, SP-08). Every call uses the interview-session token plus a DPoP proof (see the README).

## Before the interview

### Briefing — `GET /interviews/{id}/briefing`

What the desktop shows before the system check: §30's instructions and the itemised consent notice.

```json
{
  "instructions": ["Find a quiet, well-lit room.", "…"],
  "mandatory_checks": ["camera", "microphone", "speaker", "screen_capture", "network"],
  "notice": {
    "version": "2026-10-09",
    "items": [ { "purpose": "camera", "text": "…", "required": true }, … ]
  },
  "accommodations": { "requested": [], "approved": [] },
  "answer_mode": "voice",
  "third_eye": "optional"
}
```

### System checks — `POST /interviews/{id}/system-checks`

Body:

```json
{
  "app_version": "1.4.0",
  "os": "Windows 11 26200",
  "results": [
    { "check": "camera", "status": "pass", "value": "Integrated Webcam 1280x720@30", "detail": null },
    { "check": "microphone", "status": "pass", "value": "-18 dBFS peak" },
    { "check": "speaker", "status": "pass" },
    { "check": "screen_capture", "status": "pass", "value": "2 displays" },
    { "check": "network", "status": "warn", "value": "4.2 Mbps up, 38 ms RTT, LiveKit ok" },
    { "check": "cpu", "status": "pass", "value": "8 logical, 23% busy" },
    { "check": "memory", "status": "pass", "value": "6.1 GB free" },
    { "check": "disk", "status": "pass", "value": "41 GB free" },
    { "check": "displays", "status": "warn", "value": "2" },
    { "check": "privacy", "status": "pass", "value": "camera and microphone allowed" },
    { "check": "third_eye", "status": "skipped" },
    { "check": "media_foundation", "status": "pass", "value": "H.264 encoder present" },
    { "check": "webview2", "status": "pass", "value": "131.0.2903.86" }
  ]
}
```

- **Check names:** §29's eleven, plus `media_foundation` and `webview2`.
- **`status`:** one of `pass`, `warn`, `fail` or `skipped`.
- **`201`:** `{ "id": "uuid", "passed": true, "failed_mandatory": [] }`. Which checks are mandatory comes from the interview's policy, and `passed` is false when a mandatory one isn't `pass`.

### Consents — `POST /interviews/{id}/consents`

- **Body:** `{ "notice_version": "2026-10-09", "items": [ { "purpose": "camera", "accepted": true }, … ] }`
- **Purposes:** §83's ten: `camera`, `microphone`, `screen`, `audio`, `video`, `third_eye`, `transcript`, `coding_activity`, `system_telemetry`, `proctoring_events`.
- **`201`:** `{ "id": "uuid", "complete": true, "missing": [] }`.
- **Declining:** `accepted: false` on a purpose the policy needs makes `complete` false. The desktop then offers the accommodation request.

### Accommodation request — `POST /interviews/{id}/accommodations`

- **Body:** `{ "kinds": ["extended_time", "text_answers", "breaks", "assistive_technology", "relaxed_gaze", "third_eye_waiver"], "note": "…" }`.
- **`201`:** `{ "id", "status": "requested" }`. A recruiter approves it in the web app.

## The interview

### Start — `POST /interviews/{id}/start`

- **Body:** `{ "system_check_id": "uuid", "consent_id": "uuid" }`.
- **`200`:**

```json
{
  "livekit_url": "wss://livekit.hirevion.localhost",
  "room": "iv-<uuid>",
  "participant_identity": "candidate-<uuid>",
  "participant_token": "eyJ…",
  "token_expires_at": "…",
  "state": {
    "status": "in_progress",
    "started_at": "…",
    "deadline_at": "…",
    "remaining_seconds": 2700,
    "third_eye": "optional",
    "workspace": "none",
    "answer_mode": "voice"
  }
}
```

- **What the participant token allows:** publishing the microphone, the camera and a screen-preview track, and sending and receiving data on the topics below. It allows nothing else.
- **Resuming:** calling start again after a disconnect resumes the same interview, by the resume policy, and returns `"status": "in_progress"`.
- **Errors:**
  - `409 checks-incomplete`;
  - `409 consents-missing`;
  - `409 third-eye-required` (the policy needs a paired phone);
  - `409 interview-not-open`;
  - `410 interview-expired`;
  - `409 resume-limit-reached`.

### Data channel topics (LiveKit, reliable, JSON)

**`hv.state`** goes from the agent to the desktop:

```json
{
  "voice": "listening | thinking | speaking | waiting | paused | ended",
  "question": { "id": "uuid", "index": 3, "text": "…", "type": "coding", "time_limit_seconds": 600,
                "workspace": "none | code | whiteboard", "languages": ["python"] },
  "remaining_seconds": 1830,
  "notice": null
}
```

- **Captions** use LiveKit's transcription stream; there's no separate topic.
- **`notice`** carries proctoring nudges, for example `{ "kind": "camera_covered" }`.

**`hv.control`** goes from the desktop to the agent: `{ "action": "done_answering" | "repeat" | "need_a_moment" }`.

### The other interview endpoints

| Call | Body | Answer |
|---|---|---|
| `GET /interviews/{id}/session` | — | `{ "state": {…, as in start} }` (for recovery after a restart; the clock offset comes from `GET /time`) |
| `POST /interviews/{id}/answer` (text-answer mode, PRD §90) | `{ "question_id": "uuid", "text": "…" }` | `202 { "state": {…} }`: in text mode the state already holds the next question; in voice mode it may not yet |
| `POST /interviews/{id}/workspace` (code or whiteboard snapshot) | `{ "question_id", "kind": "code" \| "whiteboard", "language": "python", "content": "…" }` | `202` |
| `POST /interviews/{id}/complete` | `{ "reason": "finished" \| "candidate_ended" }` | `200 { "status": "completed" }` |

- **After completion:** the desktop drains its upload queue (recordings.md) before saying it's safe to close.
- **Coding:** coding runs and submissions belong to SP-16's own contract, added later.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane C.
  - Added `GET /interviews/{id}/briefing`: the instructions, mandatory checks and consent notice the desktop shows before the system check (§30), so their text comes from the server.
  - The session state gains `answer_mode` (`voice`, or `text` when the text-answer accommodation applies).
  - `POST /interviews/{id}/answer` answers `202` with the latest `state`.
  - A consent whose `notice_version` isn't the current one is `409 notice-outdated` (fetch the briefing again); an unknown check name is `422 unknown-check`.
