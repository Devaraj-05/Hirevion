# C8-3 Third-eye preview and placement check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the candidate sees the phone's live picture on the desktop and can continue only when the picture shows them and their whole laptop (product owner, 2026-11-15). The phone can switch between its rear and front cameras.

**Architecture:**
- The API gives the desktop a hidden, subscribe-only LiveKit token for the interview's room while a pairing is connected and the interview hasn't started.
- The desktop watches only the phone's camera track. A worker runs MediaPipe's EfficientDet-Lite0 object detector on it, on the device; nothing is uploaded.
- A pure framing function turns detections into a verdict: a person and a laptop (or keyboard) fully inside the picture, held for 3 s, makes it "green". Then the candidate confirms, and Continue unlocks.
- The confirmed check is recorded as an interview event (`third_eye_placement_confirmed`) with the scores, so the recruiter can see it.

**Tech stack:** FastAPI and the LiveKit server SDK (API); Tauri 2 / Rust `send_path` (desktop native); React, livekit-client and `@mediapipe/tasks-vision` `ObjectDetector` (desktop webview); livekit-client `restartTrack` (phone page).

## Global constraints

- **Product-owner decisions, 2026-11-15:**
  - automatic detection plus the candidate's confirmation;
  - strict: no way past the phone step without green;
  - the phone opens on the rear camera and has a "Switch camera" button.
- The desktop never downloads models or code at run time: the model is bundled in `public/models` with its source, licence (Apache-2.0) and SHA-256.
- The preview token is hidden, can't publish, and expires within 10 minutes. It is issued only for the caller's own interview, only before the start, and only while the pairing is connected.
- Synthetic data only; no Claude attribution; TDD; the desktop e2e stays green.

## Tasks

### Task 1: Phone page — Switch camera
- **Files:** `third-eye/src/livekit.ts`, `third-eye/src/App.tsx`, `third-eye/src/camera.ts` (new), `third-eye/src/camera.test.ts` (new).
- `cameraConstraints(facing)` gives the 720p/15 fps constraints for `environment` or `user`; `nextFacing` flips between them.
- The button calls `LocalVideoTrack.restartTrack(cameraConstraints(next).video)`. The publication (and its recording) stays the same.
- Test: the constraints for each facing, and the flip.

### Task 2: API — preview token and placement record
- **Files:** `hirevion_core/interview_session/media.py` (`preview_token`), `hirevion_core/third_eye/service.py` (`preview`, `placement`), `hirevion_api/third_eye/routes.py` + `schemas.py`, `test_authorization_matrix.py`, `backend/api/tests/test_third_eye_api.py`, `docs/api/contracts/third-eye.md`.
- `POST /third-eye/pairings/{id}/preview` → `{livekit_url, token, phone_identity, expires_at}`:
  - `409 third-eye-not-connected` unless the pairing is the interview's current one and connected;
  - `409 interview-not-open` once the interview has started or ended.
- `POST /third-eye/pairings/{id}/placement` with `{person, laptop, confirmed: true}` (scores 0–1) → `204`. It records the event `third_eye_placement_confirmed` with the scores.
- Tests: token grants (hidden, subscribe-only, room, TTL ≤ 10 min); the refusals; the event recorded.

### Task 3: Desktop native — two commands
- **Files:** `src-tauri/src/app/third_eye.rs`, `stub.rs`, `lib.rs` (handler list), `src/native/commands.ts`.
- `third_eye_preview(interview_id)` and `third_eye_placement(interview_id, person, laptop)`, through `send_path` like the pairing calls. In stub mode, the preview answers `null`: the webview then uses a stub detector that turns green after 2 s.
- Test: the path built for each command; a pairing id is checked before it is used.

### Task 4: Desktop webview — preview, detector and the green gate
- **Files:**
  - `src/third-eye/framing.ts` and `framing.test.ts` (new);
  - `src/vision/object-worker.ts` (new);
  - `src/third-eye/preview.tsx` (new);
  - `src/screens/third-eye.tsx`;
  - i18n;
  - `public/models/efficientdet_lite0.tflite` and the models `README.md`;
  - `e2e/desktop.e2e.mjs`.
- `framing(detections, width, height)`:
  - a person (score ≥ 0.5) and a laptop or keyboard (≥ 0.4), each box inside the frame with a margin of 2% of the side;
  - says which is missing or cut off.
- `Steady`: green after 3 s of consecutive green frames, and back to not-green after 1 s without.
- The preview shows the video with the detection boxes (green when inside, amber when cut off), plus a status line: "In the green zone", or what to fix.
- Gate: Continue is enabled only when green, the checkbox "My phone shows me and my whole laptop" is ticked, and the placement was recorded.
- Tests: the framing cases (none, person only, laptop only, cut at an edge, both); the steady timing.

### Task 5: Docs, review, merge, live check
- ADR-0042 (on-device placement check, preview token, strict gate); threat model rows for the preview token; PENDING_TASKS (C8-3) and STATUS.
- `/code-review`, then merge.
- The owner pairs a real phone: the picture appears on the desktop, goes green with them and the laptop in view, and the switch to the front camera keeps the stream.

## Exit criteria

- Unit and API tests are green, and the desktop e2e (stub) passes through the gate.
- A real phone's picture shows on the desktop and turns green only with the candidate and the laptop in view (the owner's check).
