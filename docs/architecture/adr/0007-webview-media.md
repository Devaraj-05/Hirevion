# ADR-0007: Camera and microphone recording and face detection in WebView2

- **Status:** Accepted
- **Date:** 2026-09-29
- **Sub-project:** SP-00d (spike 3)

## Context

The desktop app's webview (Tauri 2 on WebView2) needs four things:

- Record the candidate's camera and microphone into 10-second segments that Rust encrypts and uploads (PRD §49–51).
- Run on-device face detection for proctoring at 10 fps or more (PRD §56).
- Get camera access without a browser permission prompt the candidate could misread.
- Never grant any other permission.

Measured with the app's unattended spike runner (`HV_SPIKE=media:45:faces=<gpu|cpu|off>`), which writes a JSON report with the CPU use of the whole process tree (app plus every WebView2 process):

- **Hardware:** the development PC (i5-8350U, Intel UHD 620, WebView2 153).
- **Input:** Chromium's fake camera and microphone (`--use-fake-device-for-media-stream`, a synthetic 1280×720 pattern and tone) rather than recording the developer. WebView2 still raises its permission event for fake devices, so the permission policy is exercised.
- **Builds:** the dev server and the built app (assets from `http://tauri.localhost` under the release CSP).

| Run (45 s, 720p/15 fps camera + mic) | Process-tree CPU | Face detection | Inference p50 / p95 |
|---|---|---|---|
| Recording only | 4.2 % | — | — |
| Recording + face detection, GPU delegate | 6.8 % | 16 fps | 9.9 / 16.2 ms |
| Recording + face detection, CPU delegate | 7.6 % | 16 fps | 13.0 / 20.1 ms |
| Built app, recording + GPU face detection | 7.7 % | 16 fps | 9.8 / 16.2 ms |

Also measured:

- **Prompts:**
  - The camera and microphone opened in 470 ms with no prompt.
  - A geolocation request from the same page was denied, also with no prompt.
- **Encoding:**
  - WebCodecs reports hardware H.264 support (`prefer-hardware`).
  - 0 of 682 frames dropped; the encoder queue never exceeded 2.
- **Segment files:**
  - Each 10-second segment is 265–370 KB, about 2 MB per minute for video at 1 Mbps plus Opus audio at 32 kbps.
  - Finalizing a segment in memory took 2–6 ms.
  - Handing it to Rust as raw IPC bytes took 13–28 ms.
- **Playback checks** (ffprobe):
  - Every segment holds H.264 Main with 150 frames and Opus with 500 frames, each 10.0 s.
  - Audio starts within 13 ms of video.
  - Segments join with `-c copy` with strictly increasing timestamps.

Four problems found and fixed during the spike:

1. **The tracks use different clocks.** Chromium stamps camera frames with the system capture clock (about 123,726 s here) but microphone data with time since the stream started (about 1.8 s). Every audio chunk was being discarded as "before the segment". Each track's clock is now mapped onto `performance.now()` at its first sample.
2. **Declaring a frame rate to Mediabunny snaps timestamps to 1/15 s.** Frames that arrive slightly early or late then share a timestamp. No frame rate is declared now, and a frame without a duration gets 1/15 s.
3. **Vite's dev server refuses dynamic imports from `public/`,** which is how MediaPipe loads its WebAssembly loader. Development loads it from the package; builds use a copy.
4. **React StrictMode runs effects twice in development,** so the unattended run started twice. A ref guards it.

## Decision

- **Permissions:**
  - A WebView2 `PermissionRequested` handler grants the camera and microphone only when the requesting page's origin is exactly `http://tauri.localhost`, or the Vite dev server in debug builds. The origin is compared as scheme + host + port with the `url` crate.
  - Every other permission, and every other origin, is denied.
  - The status bar is off, and the default context menu is off in release builds.
- **Recording pipeline:**
  - `MediaStreamTrackProcessor` feeds the WebCodecs `VideoEncoder`: H.264 Main level 3.1, 1 Mbps, 15 fps, `prefer-hardware`, realtime mode. The software encoder is the fallback when hardware isn't supported.
  - The microphone feeds an `AudioEncoder` (Opus, 48 kHz, mono, 32 kbps).
  - Mediabunny (MPL-2.0, used unmodified) builds one fast-start MP4 per 10-second segment in memory.
  - The first frame of each segment is a keyframe.
  - Finished segments go to Rust as raw IPC bytes (`tauri::ipc::Request`), never as JSON arrays.
- **Face detection:**
  - MediaPipe Tasks Vision 1.0.1 runs in a module worker, using the GPU delegate on an `OffscreenCanvas`, fed `ImageBitmap`s at the target rate and skipping frames while busy.
  - The CPU delegate is a close second; the app falls back to it when WebGL is unavailable.
  - The BlazeFace short-range model (Apache-2.0) is bundled with its SHA-256 (`public/models/README.md`). The app never downloads models or code at run time.
  - Only MediaPipe's ES-module WebAssembly build is shipped: 12 MB instead of 34 MB.
- **CSP:** the only additions are `script-src 'wasm-unsafe-eval'` (WebAssembly) and `worker-src 'self' blob:`.

## Consequences

- Camera, microphone and face detection together cost about 7–8 % of this laptop's CPU. That leaves room for screen recording (ADR-0006, about 1 %), LiveKit publishing and the interview UI within the budget.
- **Upload:** about 2 MB per minute of camera and microphone recording, plus about 0.4–1 MB per minute of screen, so a 45-minute interview uploads roughly 110–135 MB.
- **Follow-ups:**
  - **SP-08:** add the remaining WebView2 hardening, such as browser accelerator keys off. Report a `CLIENT_INTEGRITY_WARNING` when `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` is set; the spike used it for fake devices, and a candidate could use it to feed a fake camera.
  - **SP-08 / SP-15a:** re-measure with a real webcam, with the candidate's consent. USB webcams that deliver MJPEG add decoding cost.
  - **SP-12:** wire in encryption, the upload queue and acknowledgement. Fall back to `MediaRecorder` when WebCodecs H.264 is unavailable. Verify A/V sync on real devices over a full interview.
  - **SP-15a:** measure the face landmarker (needed for gaze), which is heavier than the detector.
