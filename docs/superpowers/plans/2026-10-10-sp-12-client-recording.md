# SP-12 Recording pipeline, desktop client — plan

- **Lane:** B (the local Windows PC). The server side (upload URLs, hash check, `media-worker`, Egress) is lane D.
- **Master plan:** §14 SP-12 and §6.11. **ADR:** 0006 (capture and encode settings, kept unchanged).
- **Contract:** `docs/api/contracts/recordings.md` (upload URL → PUT → hash-verified ack → recovery listing).

**Goal:** every display, the camera and the microphone are recorded in 10-second segments that are encrypted at rest, uploaded in the background without starving live media, acknowledged by the server, and only then deleted. A crash, a kill or a lost network loses no acknowledged segment and at most the one segment being written.

## Decisions

- **Three Rust crates, one pipeline:** `recorder` (screens) and the webview (camera, mic) produce plaintext segments in memory → `segment-store` encrypts and records them → `uploader` sends them and purges after the ack. The app crate (SP-08b) only wires them together.
- **`hv-recorder` (productionised spike):**
  - ADR-0006 settings are the defaults (`RecorderConfig::default()`): WGC at 15 fps, GPU NV12, H.264 Main, constant quality 50, one keyframe per 10-second segment, hardware encoder first, writer opened ahead of time.
  - Segments never touch the disk unencrypted: the recorder hands each finished MP4 (bytes in memory) to a `SegmentSink`; the old plaintext files and `manifest.jsonl` go away (the bench example writes files itself).
  - Tracks: `screen-1` is the primary display, then the others in Windows' order.
  - Timing: `started_at` is in server ms, computed from the recording's server-time origin plus the frame clock (`seq × segment length`), so it never drifts; `duration_ms` comes from the frames actually written.
  - A display that fails is reported to the sink (`display_failed`), so SP-08b can raise the gap.
- **`hv-segment-store` (new):**
  - One file per segment: a small header (magic, version, metadata JSON) authenticated as AES-256-GCM associated data, a random 96-bit nonce, then the ciphertext. The header lets a file whose manifest row was never committed be re-adopted after a crash.
  - The key is random per interview, kept only in the DPAPI `Vault` (`rec-key-<interview>`), and deleted with the interview's last segment.
  - The manifest is SQLite (`rusqlite`, bundled, public-domain SQLite) in WAL mode with `synchronous=FULL`.
  - Each row: interview, track, seq, `started_at` (server ms), duration, bytes, SHA-256 of the **plaintext**, container, codec, state, attempts, server `segment_id`, last error.
  - States: `captured → queued → uploading → uploaded → acknowledged → purged`, with the retry edges `uploading → queued` and `uploaded → queued` (422/404), and `captured|queued|uploading|uploaded → acknowledged` (409 or recovery). Any other edge is refused.
  - Writes: temp file → fsync → rename → manifest row. On open: temp files are deleted (the one in-flight segment), orphan files are adopted from their header, `uploading` rows go back to `queued`, and acknowledged files still on disk are purged.
  - `track`, `container` and `codec` are validated against the contract (screen: MP4/H.264; camera: MP4/H.264 or WebM/VP8; mic: WebM/Opus or MP4/AAC).
- **`hv-uploader` (new):**
  - DPoP calls go through `ApiClient::send` with the interview-session token from a `TokenSource`; the PUT is plain reqwest to the SAS URL with the returned headers and an explicit `Content-Length` (Blob storage refuses chunked uploads).
  - HTTPS only, except `http://127.0.0.1` / `localhost` in debug builds.
  - One segment at a time, oldest first. A failing segment waits for its own backoff, so it never blocks the others.
  - Backoff: exponential from 500 ms with equal jitter, capped at 30 s; `Retry-After` is honoured.
  - Bandwidth: a token bucket throttles the PUT body in 64 KiB chunks; the caller lowers or lifts the cap at any time (live media first).
  - Recovery on start: `GET /recordings/interviews/{id}/segments`; local rows the server already holds (`≤ acknowledged_through`, not in `missing`) are marked acknowledged and purged, everything else uploads.
  - `409 segment-acknowledged` → acknowledged; `422 hash-mismatch` / `404 blob-missing` → a new URL and upload again; the local file is deleted only after the ack.
- **Webview, `src/recording/` (TypeScript):**
  - Camera: WebCodecs H.264 (hardware first) in MP4 via mediabunny, VP8/WebM when H.264 can't be encoded; mic: Opus in WebM. Separate tracks, as the contract lists them.
  - Every segment starts with a keyframe, so each file plays on its own.
  - MediaRecorder fallback (WebM, one recorder restarted every 10 s) when WebCodecs or `MediaStreamTrackProcessor` is missing.
  - Each finished segment goes to Rust as raw bytes through `recording_store_segment`, with track, seq, `started_at` (server ms), duration, container and codec in headers. The interview id comes from Rust's recording state, never from the webview.
  - Timing math is pure and tested: capture timestamps map to `performance.now()`, then to server ms with the offset Rust reports (`recording_clock`).
- **Not in this part (SP-08b wires them):** the Tauri commands and state, `RECORDING_STATUS` in the UI, evidence snapshots, and Egress/`media-worker` (lane D).

## Tasks

1. Plan (this file).
2. `hv-segment-store`: tests first (round trip, wrong key / tampered header refused, plaintext SHA-256, state machine, crash recovery including a killed child process), then the crate.
3. `hv-uploader`: wiremock tests first (URL request, PUT with headers, ack, 409/422/404, backoff schedule, recovery listing, bandwidth math, chaos: kill mid-upload and a dropped network), then the crate.
4. `hv-recorder`: timing and track-name tests, the sink API, the bench example on the sink, a real ~10-second capture test (`#[ignore]`, run once by hand).
5. Webview `src/recording/`: Vitest for boundaries, timing and drift, then the recorders and the typed command wrapper.
6. `cargo fmt`, `clippy -D warnings`, `cargo test`, `pnpm typecheck test`, Biome; the integration note for SP-08b in the report.

## Exit criteria (master plan)

- Chaos: kill mid-upload, network failures, a crash mid-write → no acknowledged segment lost, at most one in-flight segment lost.
- Drift: segment `started_at` values in server ms put camera, mic and screen on one timeline within 100 ms.
