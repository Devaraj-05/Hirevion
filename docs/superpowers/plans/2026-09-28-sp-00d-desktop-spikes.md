# SP-00d Desktop Spikes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before SP-08, SP-12 and SP-13 are built, prove the three desktop-side risks with measured numbers:

1. Native screen capture → 10-second H.264 MP4 segments at 1080p/15 fps, within a CPU budget.
2. WebView2 media inside Tauri:
   - camera/mic permission granted automatically, only to the app's own origin;
   - WebCodecs camera+mic segments handed to Rust;
   - MediaPipe face detection at ≥ 10 fps.
3. Self-hosted LiveKit, with the desktop app and a phone joining through a quick tunnel.

Each result becomes an ADR (0006, 0007, 0008). The code stays as the seed of `ai-interviewer-desktop` (SP-08/11/12) and `third-eye` (SP-13).

**Architecture:**

- **TypeScript workspace.** A root pnpm workspace, the repo's first TypeScript packages, holds `ai-interviewer-desktop`, `third-eye` and `packages/rtc-stats`. Biome lints and formats, Vitest runs unit tests, and `tsc --noEmit` type-checks.
- **Rust workspace.** `ai-interviewer-desktop/src-tauri` is the Cargo workspace root (ADR-0001). It holds:
  - the Tauri app crate `hirevion-desktop`;
  - `crates/screen-capture` (`hv-screen-capture`): Windows Graphics Capture (WGC) of every display, with D3D11 video-processor scaling to NV12;
  - `crates/recorder` (`hv-recorder`): a Media Foundation Sink Writer H.264 segmenter that writes each MP4 into memory, plus a `capture_bench` example.
- **Desktop spike pages.** The webview (React + Vite) has two:
  - *Media:* camera+mic → WebCodecs → Mediabunny MP4 segments → Rust over raw IPC, plus a MediaPipe worker.
  - *LiveKit:* joins a room, shows the phone's camera and its connection stats.
- **Third-eye spike page.** Rear camera → LiveKit publish.
- **Tunnel path (local only).** A Caddy HTTP site on `127.0.0.1:8088` routes `/rtc*` to LiveKit and everything else to the third-eye dev server. `uv run hv eye-tunnel` then:
  - starts `cloudflared`;
  - mints a camera-publish-only token;
  - prints the phone link and a QR code.
- **Unattended runs.** For the webview measurements, the app reads `HV_SPIKE=<page>:<seconds>`. It opens that spike page, which runs by itself and reports its numbers to Rust. Rust adds the CPU time of its own process tree (app + WebView2 processes) and writes a JSON result under `ai-interviewer-desktop/spike-results/` (gitignored).

**Tech Stack:**

- Desktop native: Tauri 2 (stable 2.x), Rust edition 2024, `windows` 0.62 (Graphics.Capture, Direct3D11, DXGI, Media Foundation), `webview2-com` (the version wry uses).
- Web: React 19, Vite 8, TypeScript 7, Biome 2, Vitest 5, `mediabunny`, `@mediapipe/tasks-vision`, `livekit-client`.
- Tooling: `cloudflared` (quick tunnels) and `segno` (terminal QR codes).

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 and in the SP-00a/b/c plans applies.
- **Tests.** Pure logic is TDD'd: Rust unit tests, Vitest and pytest. Hardware-bound checks (display capture, encoder, camera) are `#[ignore]` tests or benchmark runs; their results go in the ADRs.
- **No secrets in the apps.** The desktop app and third-eye bundles contain no LiveKit or API secrets. Tokens come only from `hv` (development) and later from the backend.
- **Webview permissions.** Camera and microphone are granted only to the app's own origin: `http://tauri.localhost` in release, plus the dev-server origin in debug builds. Every other permission kind is denied.
- **Spike recordings.** Plaintext spike recordings go only to gitignored folders. Encryption at rest arrives with SP-12's segment store.
- **Initial CPU budgets** (the ADRs record the actual numbers), measured on this PC (i5-8350U, 4 cores / 8 threads, Intel UHD 620, 1920×1080):
  - screen recorder at 1080p/15 fps: ≤ 5 % of total CPU with the hardware encoder, ≤ 15 % with the software encoder;
  - camera 720p/15 + mic encode + face detection at 10–15 fps: ≤ 20 % of total CPU.
- **Toolchain versions** are pinned: `packageManager` (pnpm 12), `Cargo.lock`, `pnpm-lock.yaml`.

## File Structure

| Path | Responsibility |
|---|---|
| `package.json`, `pnpm-workspace.yaml`, `biome.json` | TypeScript workspace root: pinned pnpm, shared lint/format/typecheck/test scripts |
| `ai-interviewer-desktop/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html` | Desktop webview build (port 1420) |
| `ai-interviewer-desktop/src/main.tsx`, `App.tsx`, `routes.ts` | Shell with hash routes: Home, Media spike, LiveKit spike |
| `ai-interviewer-desktop/src/spikes/media/*` | WebCodecs segmenter, Mediabunny muxing, MediaPipe worker, fps meter |
| `ai-interviewer-desktop/src/spikes/livekit/*` | LiveKit spike page |
| `ai-interviewer-desktop/src-tauri/Cargo.toml` | Cargo workspace + app crate `hirevion-desktop` |
| `ai-interviewer-desktop/src-tauri/tauri.conf.json`, `capabilities/default.json`, `icons/*` | App config: identifier, strict CSP, NSIS per-user bundle, minimal capabilities |
| `ai-interviewer-desktop/src-tauri/src/{main,lib,permissions,spike,perf}.rs` | App entry, WebView2 permission policy, spike commands and runner, process-tree CPU sampling |
| `ai-interviewer-desktop/src-tauri/crates/screen-capture/*` | Monitors, D3D11 device, WGC capture, BGRA→NV12 scaling |
| `ai-interviewer-desktop/src-tauri/crates/recorder/*` | Frame clock, segment writer (Media Foundation), recorder loop, `capture_bench` example |
| `ai-interviewer-desktop/src-tauri/deny.toml` | cargo-deny: license allowlist, advisories, sources |
| `third-eye/*` | Vite + React phone page (port 5174): rear camera → LiveKit |
| `packages/rtc-stats/*` | Shared TS: summarise WebRTC stats (candidate type, protocol, RTT, fps, bitrate) |
| `tools/devcli/src/hirevion_devcli/livekit.py` | LiveKit token grants, phone link, tunnel-URL parsing, LAN IP |
| `tools/devcli/src/hirevion_devcli/cli.py` | `hv lk-token`, `hv eye-tunnel` |
| `infrastructure/local/caddy/Caddyfile`, `compose.yaml` | `:8088` tunnel site |
| `.github/workflows/ci.yml` | `desktop` job (Windows), `rust-licenses` job (cargo-deny) |
| `docs/architecture/adr/0006-screen-capture.md`, `0007-webview-media.md`, `0008-livekit-phone-networking.md` | Measurements and decisions |
| `docs/runbooks/local-dev.md` | Desktop dev, capture bench, phone testing |

Branches:
- `feat/sp-00d-desktop-capture`: Tasks 1–3.
- `feat/sp-00d-webview-media`: Tasks 4–5.
- `feat/sp-00d-livekit-phone`: Tasks 6–7.

Each branch: green CI → fast-forward merge to `main` → delete the branch.

---

### Task 1: TypeScript workspace, Tauri 2 skeleton and CI

**Interfaces:**
- **Produces:**
  - the root scripts `pnpm lint`, `pnpm typecheck` and `pnpm test`;
  - the Tauri app with identifier `com.hirevion.interview`, dev URL `http://localhost:1420` and release origin `http://tauri.localhost`;
  - `routes.ts`, which exports `type Route = "home" | "media" | "livekit"` and `parseRoute(hash: string): { route: Route; params: URLSearchParams }`.

- [ ] Upgrade the global pnpm to the pinned version (`npm install -g pnpm@12.6.0`).
- [ ] Create the workspace root:
  - `package.json`: private, `packageManager: pnpm@12.6.0`, `engines.node >=24 <25`, and the scripts `lint` (`biome check .`), `format` (`biome format --write .`), `typecheck` (`pnpm -r typecheck`) and `test` (`pnpm -r test`).
  - `pnpm-workspace.yaml`.
  - `biome.json`: ignore `dist`, `target`, `gen`, `public/mediapipe`, and every `.venv`.
- [ ] Scaffold `ai-interviewer-desktop` (Vite + React + TS strict; port 1420, `strictPort`). Test first: `parseRoute("#/media?auto=60")` returns `{ route: "media", params.get("auto") === "60" }`, and unknown hashes return `home`. Then implement `routes.ts` and the shell.
- [ ] Scaffold `src-tauri`:
  - The workspace `Cargo.toml` (members `.` and `crates/*`, shared `[workspace.lints]`, `unsafe_op_in_unsafe_fn = "deny"`, `clippy::undocumented_unsafe_blocks = "warn"`) and the app package (`hirevion-desktop`, lib `hirevion_desktop_lib`).
  - `build.rs`, `main.rs` (`windows_subsystem = "windows"` in release) and `lib.rs` (`run()`).
  - `tauri.conf.json`: strict CSP, `bundle.targets = ["nsis"]` with `installMode: "currentUser"`, and `app.withGlobalTauri = false`.
  - `capabilities/default.json` with only `core:default`.
  - Icons generated from a generated 1024 px PNG with `pnpm tauri icon`.
- [ ] Add `deny.toml`. Allowed licenses: MIT, Apache-2.0 (with the LLVM exception), BSD-2/3-Clause, ISC, Zlib, Unicode-3.0, MPL-2.0, CDLA-Permissive-2.0, BSL-1.0 (Boost). Add anything else only after review, with a comment. Unknown registries and git sources are denied.
- [ ] Add CI:
  - A `desktop` job on `windows-2025`:
    - pnpm install `--frozen-lockfile`, then lint, typecheck, test, and the Vite build;
    - Rust stable with rustfmt and clippy, using the rust-cache action;
    - `cargo fmt --all --check`, `cargo clippy --workspace --all-targets --locked -- -D warnings` and `cargo test --workspace --locked`.
  - A `rust-licenses` job running `EmbarkStudios/cargo-deny-action@v2` against `ai-interviewer-desktop/src-tauri/Cargo.toml`.
- [ ] Verify locally: all the commands above; `pnpm tauri dev` opens the window with the Home page.
- [ ] Commit `feat(desktop): add Tauri 2 app skeleton and pnpm workspace`.

### Task 2: Screen capture and segment writer (TDD for pure logic)

**Interfaces:**

- `hv_screen_capture::geometry::fit_even(src: Size, max: Size) -> Size`
  - Preserves the aspect ratio, never upscales, and keeps even dimensions.
- `hv_screen_capture::monitors::enumerate() -> Result<Vec<MonitorInfo>>`
  - `MonitorInfo { handle: HMONITOR, name: String, size: Size, primary: bool }`
- `hv_screen_capture::device::GpuDevice::new() -> Result<GpuDevice>`
  - A D3D11 device with BGRA and video support, multithread-protected.
- `hv_screen_capture::capture::MonitorCapture::start(&GpuDevice, &MonitorInfo) -> Result<MonitorCapture>`
  - `latest(&self) -> Option<LatestFrame>`, where `LatestFrame` holds the texture and a capture timestamp.
  - `stop(self)`
- `hv_screen_capture::convert::Nv12Converter::new(&GpuDevice, src: Size, dst: Size) -> Result<Self>`
  - `convert(&mut self, &ID3D11Texture2D) -> Result<ID3D11Texture2D>`
- `hv_recorder::clock::FrameClock { fps: u32, frames_per_segment: u32 }`
  - `sample_time(frame: u64) -> i64` (100 ns units, no cumulative drift)
  - `frame_duration(frame: u64) -> i64`
  - `position(frame: u64) -> SegmentPosition { seq: u64, index: u32 }`
- `hv_recorder::writer::SegmentWriter::new(&GpuDevice, EncoderConfig) -> Result<Self>`
  - `write(&mut self, &ID3D11Texture2D, time: i64, duration: i64) -> Result<()>`
  - `finish(self) -> Result<Vec<u8>>`
  - `encoder_name(&self) -> String`
- `hv_recorder::mp4::looks_like_mp4(bytes: &[u8]) -> bool`
  - True when the top-level boxes include `ftyp` and `moov`.
- `hv_recorder::stats::{cpu_percent, percentile}`

Steps:

- [ ] Tests first for the pure helpers:
  - `fit_even`: 3840×2160 → 1920×1080; 2560×1600 → 1728×1080; 1366×768 is unchanged; 1921×1081 → 1918×1080. Odd results round down to even.
  - `FrameClock` at 15 fps with 150 frames per segment:
    - frame 150 is `{seq 1, index 0}`;
    - `sample_time(15 * 3600)` equals exactly 36 000 000 000 (no drift);
    - the durations of 15 consecutive frames sum to exactly 10 000 000.
  - `looks_like_mp4` accepts a minimal hand-built `ftyp`+`moov` buffer and rejects random bytes and truncated boxes.
  - `cpu_percent(Δcpu = 8 s, Δwall = 10 s, cpus = 8)` returns 10.0.
  - `percentile`: the same contract as the Python helper (linear interpolation; an empty input is an error).
- [ ] Implement the Windows parts with the `windows` crate. Every `unsafe` block gets a `// SAFETY:` comment.
  - `EnumDisplayMonitors`.
  - `D3D11CreateDevice` (`BGRA_SUPPORT | VIDEO_SUPPORT`) plus `ID3D11Multithread::SetMultithreadProtected`.
  - WGC:
    - `IGraphicsCaptureItemInterop::CreateForMonitor`;
    - `Direct3D11CaptureFramePool::CreateFreeThreaded` (BGRA8, 2 buffers);
    - a session with cursor capture on;
    - a `FrameArrived` handler that copies into the "latest" texture.
  - The D3D11 video processor: BGRA → NV12, with scaling.
  - `SegmentWriter`:
    - `MFCreateSinkWriterFromURL` over `MFCreateMFByteStreamOnStream(CreateStreamOnHGlobal)`;
    - attributes `MF_TRANSCODE_CONTAINERTYPE = MPEG4`, `MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS = 1` and `MF_SINK_WRITER_D3D_MANAGER`;
    - H.264 Main output at the configured bitrate, frame size and rate; NV12 input;
    - samples wrap `MFCreateDXGISurfaceBuffer`;
    - the encoder name is read from the stream's transform (`MFT_FRIENDLY_NAME_Attribute`).
  - A `--software` option sets `MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS = 0`, for the comparison.
- [ ] Add an ignored integration test, `crates/recorder/tests/capture_smoke.rs`. It records the primary monitor for 3 s with 1-second segments and asserts:
  - there are at least 3 segments;
  - every segment passes `looks_like_mp4`;
  - the total frames are 45 ± 2.
- [ ] Commits: `feat(desktop): add capture geometry, frame clock and mp4 checks`, then `feat(desktop): add WGC capture and Media Foundation segment writer`.

### Task 3: Recorder loop, benchmark and ADR-0006

**Interfaces:**
- `hv_recorder::Recorder::start(RecorderConfig) -> Result<Recorder>`
  - One thread per display.
  - Paced at `fps`: each tick takes the latest frame, or repeats the previous one.
  - The writer rotates every `frames_per_segment` frames. The next writer is created ahead of time, and the old one is finished on a finalizer thread.
  - `stop(self) -> Result<RecorderReport>`
- Each finished segment writes:
  - the file `<out>/display-<n>/<seq:06>.mp4`;
  - a `<out>/manifest.jsonl` line `{display, seq, started_unix_ms, frames, bytes, sha256, finalize_ms}`.
- `RecorderReport`: frames written and expected, repeated frames, a finalize p95, encoder names, and a CPU % from `GetProcessTimes` over the run.

Steps:

- [ ] Implement `Recorder` and `examples/capture_bench.rs`.
  - Arguments: `--seconds`, `--fps`, `--segment-seconds`, `--max-width`, `--max-height`, `--bitrate`, `--out` and `--software`.
  - Output: a line per segment and a summary.
- [ ] Measure on this PC with a release build, for the hardware and software encoders:
  - 60 s of an idle desktop;
  - 60 s of activity (a video playing and a page scrolling).
- [ ] Verify the output with ffprobe (Docker ffmpeg image or winget FFmpeg):
  - every segment is H.264 at 1920×1080 and 15 fps;
  - the six segments join with the concat demuxer (`-c copy`) into one file of about 60 s that plays through.
- [ ] Write ADR-0006 with:
  - the numbers: CPU, bytes per minute, the finalize/rotation stall, and the encoder names;
  - the chosen defaults: bitrate, GOP, and whether the writer is pre-created;
  - follow-ups for SP-12 (encryption, upload) and SP-11 (display-change handling).
- [ ] Update the runbook (desktop development and the capture bench).
- [ ] Commits: `feat(desktop): add recorder loop and capture benchmark`, then `docs: add ADR-0006 screen capture`.
- [ ] Finish the branch: green CI, fast-forward merge, delete the branch.

### Task 4: WebView2 permission policy, raw IPC and the spike runner (TDD for pure logic)

**Interfaces:**
- `permissions::decide(kind: PermissionKind, origin: &str, allowed: &[&str]) -> Decision`
  - Allows Camera and Microphone only for allowed origins; denies everything else.
- `permissions::install(&tauri::Webview)`
  - Windows only.
  - Uses `with_webview` → `ICoreWebView2::add_PermissionRequested` → `decide`.
  - Also sets `SetIsStatusBarEnabled(false)`; in release, `SetAreDefaultContextMenusEnabled(false)` too.
- `#[tauri::command] spike_save_segment(request: tauri::ipc::Request) -> Result<SavedSegment, String>`
  - The body is raw bytes; the headers are `x-hv-kind` and `x-hv-seq`.
  - Saves to `<app_local_data>/spike-media/`.
  - Returns `{ bytes, micros }`.
- `#[tauri::command] spike_report(report: serde_json::Value)`
  - Merges `perf::tree_cpu_percent()` over the run and writes `spike-results/<page>-<unix>.json`.
  - With `HV_SPIKE`, exits the app afterwards.
- `perf::tree_cpu_percent(since: CpuSnapshot) -> f64`
  - Sums this process and its descendants, using Toolhelp32 and `GetProcessTimes`.
- `spike::from_env(value: &str) -> Option<SpikeRun { page: String, seconds: u32 }>`

Steps:

- [ ] Tests first:
  - `decide` covers these cases:
    - camera from the release origin → allow;
    - microphone from the dev origin in debug → allow;
    - camera from `https://evil.example` → deny;
    - geolocation / notifications / clipboard-read from our own origin → deny;
    - the origin compared by scheme + host + port, never by prefix (`http://tauri.localhost.evil.com` → deny).
  - `from_env("media:60")` → page `media`, 60 seconds; bad input → `None`.
  - The CPU-tree math, over a fake process table.
- [ ] Implement, then register the commands.
- [ ] The app adds only the spike commands to its capability, and only in debug builds. Release builds don't expose them.
- [ ] Commit `feat(desktop): add WebView2 permission policy and spike runner`.

### Task 5: Media spike page (WebCodecs + Mediabunny + MediaPipe) and ADR-0007

**Interfaces:**
- `SegmentPlanner(segmentUs = 10_000_000)`
  - `segmentOf(timestampUs): number`
  - `isFirstFrameOf(timestampUs): boolean`, which asks for a keyframe
  - `relative(timestampUs): number`, the timestamp relative to the segment start in seconds
- `FpsMeter(windowMs)` with `tick(nowMs)` and `fps(nowMs)`.
- `startMediaSpike(options): Promise<MediaSpikeResult>`.

Steps:

- [ ] Tests first (Vitest):
  - segment boundaries at exactly 10 s;
  - the first frame of each segment requests a keyframe;
  - relative timestamps start at 0 in each segment;
  - `FpsMeter` over a synthetic 15 Hz tick stream returns 15 ± 0.5.
- [ ] Capture and encode:
  - Open the camera at 1280×720, 15 fps, and the microphone.
  - `MediaStreamTrackProcessor` feeds a `VideoEncoder`:
    - AVC Main, 1 Mbps, `prefer-hardware`, realtime;
    - the result of `isConfigSupported` is recorded.
  - The microphone feeds an `AudioEncoder` (Opus, 48 kHz, mono, 32 kbps).
- [ ] Segments:
  - Each 10-s segment is its own Mediabunny `Output`: `Mp4OutputFormat`, `BufferTarget`, and encoded-packet sources for video and audio.
  - Finalized bytes go to `spike_save_segment` over raw IPC.
- [ ] Face detection:
  - A MediaPipe `FaceDetector` (GPU delegate, with a CPU fallback) runs in a module worker.
  - `ImageBitmap`s are transferred at 15 fps.
  - Record the achieved fps and the inference time p50/p95 for both delegates.
- [ ] Assets:
  - The WASM files are copied from the package into `public/mediapipe/` by a `predev`/`prebuild` script (gitignored).
  - The model is committed with its SHA-256 in `public/models/README.md`.
- [ ] Tighten the CSP for this page: `script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self' blob:`, `media-src 'self' blob: mediastream:`.
- [ ] Measure unattended with `HV_SPIKE=media:60`, both with and without face detection. Confirm:
  - no permission prompt appears;
  - a geolocation request from the page is denied.
- [ ] Write ADR-0007: WebView2 version, permission behaviour, codec support, segment sizes, IPC time, fps, CPU, and the decisions.
- [ ] Commits: `feat(desktop): add media spike with WebCodecs segments and face detection`, then `docs: add ADR-0007 webview media`.
- [ ] Finish the branch.

### Task 6: `hv` LiveKit helpers, tunnel site and third-eye spike (TDD for pure logic)

**Interfaces:**
- `livekit.Grants(room: str, can_publish: bool, can_subscribe: bool, can_publish_data: bool, sources: tuple[str, ...] = ())`
- `livekit.build_token(api_key, api_secret, *, identity, name, grants, ttl_seconds, now) -> str`
- `livekit.parse_tunnel_url(line: str) -> str | None`
  - Matches only `https://<sub>.trycloudflare.com`.
- `livekit.phone_link(tunnel_url: str, token: str) -> str`
  - Returns `<tunnel>/?t=<token>`.
- `livekit.is_lan_ip(value: str) -> bool`
  - True for RFC 1918 addresses; false for loopback and public addresses.
- `livekit.detect_lan_ip(connect) -> str | None`
- CLI commands:
  - `hv lk-token --room R --identity I [--camera-only] [--ttl 600] [--copy]`
  - `hv eye-tunnel [--room spike] [--ttl 900]`

Steps:

- [ ] Tests first:
  - the token claims: `video.roomJoin`, `room`, `canPublishSources == ["camera"]` for the phone, `canSubscribe` false, and `exp = now + ttl`;
  - `parse_tunnel_url` on real cloudflared log lines, including a decoy URL that isn't a trycloudflare one;
  - `phone_link` escaping;
  - `is_lan_ip` table;
  - `eye-tunnel` refuses to start while `LIVEKIT_NODE_IP` is loopback, and prints the detected LAN IP to use.
- [ ] Implement the commands. The QR code is printed with `segno` (add the dependency), and `--copy` uses `clip.exe`.
- [ ] Caddy and compose: add the `http://:8088` site and publish it on `127.0.0.1:8088`.
- [ ] `packages/rtc-stats`, tests first. `summarizeConnection(report)` returns the selected candidate pair's `{ protocol, localType, remoteType, rttMs }`, plus the inbound or outbound video `{ fps, width, height, kbps }`.
- [ ] `third-eye`:
  - Vite on port 5174 (`strictPort`), with `allowedHosts` of `.trycloudflare.com` and `eye.hirevion.localhost`, and HMR `clientPort` 443.
  - A page with a Start button. It opens the rear camera at 1280×720 and 15 fps, then connects to `wss://${location.host}` with the token from `?t=`.
  - It publishes the camera (no simulcast, 1.2 Mbps, 15 fps) and shows the state and stats.
  - It holds a Wake Lock.
- [ ] Commit `feat(eye): add third-eye camera spike and hv tunnel helpers`.

### Task 7: Desktop LiveKit page, measurements and ADR-0008

- [ ] The desktop LiveKit page:
  - takes a token pasted from `hv lk-token --identity desktop --copy`;
  - connects to `wss://livekit.hirevion.localhost`;
  - subscribes to the phone, renders it, and shows the `rtc-stats` summary and the time to the first frame.
  - The desktop CSP `connect-src` adds `wss://livekit.hirevion.localhost` in debug builds only.
- [ ] Verify end to end from this PC: open the tunnel link in Edge. This covers HTTPS through Cloudflare, signalling through Caddy, and media over the LAN IP.
- [ ] Record for the ADR: join time, candidate type/protocol, fps, resolution and bitrate.
- [ ] Hand the phone test to the user: the QR code from `hv eye-tunnel`, then iOS Safari and Android Chrome. Record the same numbers, plus the reconnect time after locking and unlocking the phone.
- [ ] Write ADR-0008:
  - LAN IP / node IP;
  - the firewall rule;
  - the UDP → TCP fallback;
  - the tunnel;
  - TURN for the cloud plan.
- [ ] Update the runbook's phone section.
- [ ] Commits: `feat(desktop): add LiveKit spike page`, then `docs: add ADR-0008 LiveKit and phone networking`.
- [ ] Finish the branch.
