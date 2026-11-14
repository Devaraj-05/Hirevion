# B4 (part) Desktop third eye and snapshot answers — plan

- **Lane:** B (the local Windows PC). **Master plan:** §6.4 steps 9 and 12, §6.5, §14 SP-13 and SP-14 (desktop side).
- **Contracts:** `third-eye.md` and `proctoring.md` ("Changes": `snapshot_requests`, `request_id` uploads, `started_at` with a time zone). ADR-0018, ADR-0032, ADR-0040.
- **Out of this part (still open in B4):** the coding console and whiteboard (after C6), the on-device CV detectors of SP-15b (gaze, pose, phone, obstruction).

## Decisions

- **Flow:** briefing → system check → consent → **third eye** (only when the briefing says `optional` or `required`) → ready, as §6.4 orders it. A required third eye is a mandatory system-check item that the server judges from its own view, so the check may fail on `third_eye` alone before pairing; the app then continues to consent and the phone step, which submits the same check results again once the phone is connected and hands the passing check to Ready. Ready shows `409 third-eye-required` clearly, with a way back to the phone step.
- **Rust owns the pairing:** `third_eye_pair` and `third_eye_status` call `POST /third-eye/pairings` and `GET /third-eye/pairings/{id}` with the interview-session token and DPoP. The webview gets the QR code as SVG path data (rendered in Rust with `qrcodegen`, MIT), the link as the typed fallback, and the status; never a session token. Rust remembers the pairing per interview (ids only, a small file in app data), so a restart doesn't re-pair and kick the phone; asking again with `replace` re-pairs (the server revokes the old phone). An expired, unscanned code is replaced; the QR shows again only on `revoked` or `expired`, never on `disconnected`.
- **Mode from the server:** Rust reads `third_eye` from the briefing it fetches, so the heartbeat knows `off` without trusting the webview.
- **Heartbeat `third_eye`:** `not_required` (off), `not_paired` (none, issued, expired, revoked), `connecting` (redeemed), `connected`, `disconnected`; a failing status call keeps the last value. A watcher reads the status every 5 s during the interview; the webview's status bar reads the same cached value.
- **Snapshots:** the heartbeat answer's `snapshot_requests` go once per `request_id` (deduplicated, expired ones dropped) to an answerer that lives only with the proctor session. Screen: Windows Graphics Capture of the primary display, read back once, scaled to at most 1280×720 and JPEG-encoded by WIC (built into Windows; no new licence). Camera: Rust asks the webview (`hv:snapshot-request`), which grabs one frame of the interview's own camera track as JPEG and hands it back for that `request_id` only. Upload: `POST /proctoring/evidence-uploads` with `request_id`, then a PUT to the write-only URL; retries with backoff until the two-minute expiry; `404`, `409` and `422` end it. Nothing blocks the interview.

## Tasks (tests first)

1. `hv-event-queue`: parse `snapshot_requests`, a tracker that drops repeats and expired requests, a channel from the heartbeat loop.
2. `hv-uploader`: `upload_evidence` (slot with `request_id`, PUT, hash) against wiremock.
3. `hv-screen-capture`: one-frame read-back and WIC JPEG encoding (Windows tests).
4. App: `third_eye` module (commands, QR, stub, persistence), heartbeat mapping, the watcher, the snapshot answerer and `proctoring_snapshot`.
5. Webview: flow step, the phone screen (QR, fallback, status, placement, re-pair, skip), Ready's error, the interview status bar, the camera snapshot handler; en-IN and en-US.
6. e2e: consent → phone → connected → ready on the stub.
7. Docs: runbook, threat model, Appendix A, PENDING_TASKS B4, STATUS.

## Files

`crates/event-queue/src/{snapshot,uploader}.rs`, `crates/uploader/src/evidence.rs`, `crates/screen-capture/src/{still,jpeg}.rs`, `src-tauri/src/app/{third_eye,snapshots,proctoring,services,stub,interview}.rs`, `src/screens/third-eye.tsx`, `src/third-eye/*`, `src/flow/flow.ts`, `src/interview/services.ts`, `e2e/desktop.e2e.mjs`.
