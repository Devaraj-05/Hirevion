# SP-12 Recording pipeline, server side (D2) Implementation Plan

**Goal:** PRD §50 (segmented, continuous upload), §51 (acknowledged recovery), §85 (storage layout), §91 (`RECORDING_STATUS`) and §97 ("recording viewed"), implementing `docs/api/contracts/recordings.md` exactly. The desktop half is lane B's SP-12 client. The work:
- Write-only upload URLs, one blob per segment, and hash-verified acknowledgement.
- Recovery listing after a crash.
- Continuity: a track that stops arriving raises `recording.gap` and `RECORDING_STATUS`.
- `media-worker`: one file per track and a timeline map, with ffmpeg as a separate process.
- Audited playback for recruiters.

Not in D2: Egress of the conversation audio and the third-eye video, and evidence snapshots (they need SP-09's LiveKit room and SP-13/14); the proctoring engine turning gaps into `SCREEN_CAPTURE_STOPPED` or `TELEMETRY_GAP` (SP-14).

## Architecture

- **`hirevion_core.models.recording`:** `RecordingSegment` (one row per `(interview, track, seq)`) and `Recording` (one per `(interview, track)`).
- **`hirevion_core.recordings`:**
  - `tracks`: track names, the container/codec rules, blob names (pure);
  - `segments`: asking for a URL, acknowledging, the recovery listing;
  - `continuity`: the allowed silence per proctoring level, finding stalls (pure), and the monitor that publishes events;
  - `timeline`: the timeline map, the gaps and the ffmpeg command line (pure);
  - `assembly`: downloads a track's acknowledged segments, runs ffmpeg, uploads the file and the map;
  - `worker`: the `interview.completed`/`interview.abandoned` consumer, the assembly sweep and the continuity monitor, started from `run_workers` (so `hv worker` and the API's own workers both run it).
- **The API:** `/recordings/*` for the desktop (interview-session token plus DPoP; the `interview` entries of `UNGUARDED`), and `GET /interviews/{id}/recordings` for recruiters (`reports.interview.view`, resource-scoped, audited).

## Decisions

- **Track names:** `screen-1` to `screen-8`, `camera`, `mic`. Blob folders follow §85: screens in `screen/`, the camera in `camera/`, the mic in `audio/`. A segment is `{track}-{seq:06d}.{mp4|webm}`; the assembled file is `{track}-full.{ext}` and its map `{track}-timeline.json`, in the same folder.
- **Formats:** screen `mp4`/`h264`. Camera and mic: `webm` with `vp8` or `opus`, or `mp4` with `h264` or `aac`, exactly as the contract words it. Anything else is `422 unsupported-format`.
- **Limits:** a segment is at most 50,000,000 bytes (`413 segment-too-large`; the desktop client's reading of "50 MB") and 60,000 ms (`422 segment-too-long`). `seq` starts at 0 and only increases, but may **skip numbers** (a pause over 10 s, or the MediaRecorder fallback after an early stop): a later `seq` is never refused, and skipped numbers are reported as gaps.
- **Who may upload:** the token's interview must equal the body's (`403 wrong-interview`) and the interview must have started (`409 interview-not-started`); uploads are allowed after it ends, because the desktop drains its queue then and again at its next launch. A track the interview's pinned policy doesn't record is `422 track-not-recorded` (`screen-*` need `recording.screen`, `camera` needs `recording.camera`, `mic` needs `recording.audio`; a missing key means recorded).
- **Segment states:** `requested` (a URL was issued) → `uploaded` (the acknowledgement found the blob) → `acknowledged` (size and SHA-256 match what was declared). A mismatch (wrong size, wrong hash, or a body hash other than the declared one) leaves the segment `uploaded` (in storage, not verified) with `attempts` + 1, and answers `422 hash-mismatch`; asking for a URL again puts it back to `requested`. The acknowledgement reads the blob in chunks outside any database transaction, and not at all if it is larger than declared.
- **Retries:** asking again for the same `(interview, track, seq)` returns the same `segment_id` and a fresh URL; if the declared hash or size changed it replaces the declaration. An acknowledged segment answers `409 segment-acknowledged`. No `Idempotency-Key` is needed; the uniqueness gives idempotency.
- **Recovery listing:** per track, `acknowledged_through` is the highest acknowledged `seq` (`null` when nothing is acknowledged yet) and `missing` every `seq` at or below it that is not acknowledged, including numbers that were skipped and never requested. Anything the desktop holds above `acknowledged_through` is simply unacknowledged.
- **After-the-fact tampering:** the upload URL allows overwriting the one blob for 15 minutes, also after the acknowledgement. The assembly therefore re-hashes every segment against the acknowledged SHA-256, and refuses a blob larger than declared before downloading it; a segment that no longer matches is left out and listed in the gaps as `corrupt`.
- **Continuity:** the allowed silence before a track counts as stalled, by the interview's pinned proctoring level: `off` 120 s, `basic` 60 s, `standard` 30 s, `strict` 20 s (never below twice the segment length). The monitor looks at interviews `in_progress` (the reference time is the latest of the last segment's arrival, the interview's start and the session's last connection, so a resumed interview isn't flagged at once), and also at policy-required tracks that never produced a segment.
  - `recording.gap` outbox event: `{interview_id, track, kind: "stalled" | "missing" | "corrupt", state: "open" | "closed", from_seq, to_seq, from_time, to_time}`. A stall opens with `to_seq` and `to_time` null; it closes when a segment arrives. Skipped or lost numbers are reported once, as `missing` or `corrupt`, when the track is assembled (a backlog can still bring them before then). Times are server time (ISO 8601).
  - `RECORDING_STATUS` on the interview's realtime stream (`hv:rt:interview:{id}`): `{track, status: "recording" | "stalled" | "assembled" | "assembly-pending", last_seq, acknowledged_through}`.
- **Assembly:** triggered by `interview.completed` and `interview.abandoned`, then retried by a sweep. A track waits (`assembly-pending`) while any of its segments was requested in the last `settle` seconds (default 120) and isn't acknowledged. ffmpeg runs as a separate process with the concat demuxer and `-c copy` (no re-encode), from a list file in a private temporary directory. If the binary is missing the recording stays `assembly-pending` and one warning is logged per process. A failure backs off (`next_attempt_at`) and becomes `failed` after 5 attempts. A segment acknowledged after assembly puts the recording back to `assembly-pending` so the next sweep rebuilds it. The sweep also takes tracks of ended interviews that are still `recording` (a missed event) and `assembling` ones a dead worker left behind for 30 minutes.
- **Timeline map:** per track, `{track, container, started_at, segments: [{seq, started_at, duration_ms, file_offset_ms}], gaps: [{from_seq, to_seq, from_time, to_time, reason}]}`. A file offset is the sum of the declared durations of the segments before it in the assembled file, so file time maps to server time as `started_at + (t - file_offset_ms)` inside a segment. Anchoring every segment to its own server `started_at` keeps the error to one segment's, so tracks stay in sync within the 100 ms target as long as a segment's real duration is within that of its declared one. Gaps are not filled in the file; the map is what a player uses to line tracks up.
- **Locking the cross-tenant scans:** the worker lists work through two `SECURITY DEFINER` functions owned by the scheduler's listing role (the 0013 pattern), then handles each interview in its own tenant transaction.
- **Playback:** `GET /interviews/{id}/recordings` lists the tracks with a 5-minute read URL for each assembled file and its map, and, until a track is assembled, a read URL for each acknowledged segment. It records `recording.viewed` in the audit chain.
- **Shared streams:** the `interview.completed` stream now has two groups (`transcripts`, `media`), and `StreamConsumer` deleted each message once handled, which would starve the other group. A consumer on a shared topic is built with `delete_handled=False`; the relay's `maxlen` trims the stream.

## Tasks

1. Migration 0016 and the two models (tests: tenant isolation, insert/update grants, uniqueness, models match migrations).
2. Pure modules with unit tests: tracks, timeline and the ffmpeg command, continuity.
3. Segment service and the desktop routes (tests: the contract through `DesktopClient` with real Azurite and real SAS uploads).
4. Continuity monitor and events.
5. Assembly and the worker (tests: the consumer with a fake runner; real ffmpeg only when it is on PATH).
6. Recruiter playback with audit, and the matrix rows.
7. OpenAPI and the generated client, the runbook, Appendix A, the threat model, `PENDING_TASKS.md`.
