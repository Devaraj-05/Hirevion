# Contract: recording segments

**Provider:** lane D, SP-12 server side. **Consumer:** the desktop app (lane B, SP-12 client). Every call uses the interview-session token plus a DPoP proof.

## How recording works

- **On the device:** the desktop records 10-second segments per track and keeps each one encrypted (AES-256-GCM) in its local queue.
- **Uploading:** to upload a segment, the desktop asks for a write-only URL, uploads the plaintext bytes over TLS, then asks the server to acknowledge.
- **Deleting:** the desktop deletes a local segment only after it has been acknowledged (PRD §51).

**Tracks:**
- `screen-1`, `screen-2`, … (one per display);
- `camera`;
- `mic`.

The conversation audio and third-eye are recorded on the server by LiveKit Egress and aren't uploaded by the desktop.

## Ask for an upload URL — `POST /recordings/segments`

Body:

```json
{
  "interview_id": "uuid",
  "track": "screen-1",
  "seq": 17,
  "started_at": "2026-10-12T05:03:20.000Z",
  "duration_ms": 10000,
  "bytes": 1843921,
  "sha256": "<hex>",
  "container": "mp4",
  "codec": "h264"
}
```

- **Containers and codecs:**
  - screen tracks: `mp4` with `h264`;
  - camera and microphone: `webm` with `vp8` or `opus`, or `mp4` with `h264` or `aac`.
- **`200`:** `{ "segment_id": "uuid", "upload_url": "<write-only SAS for one blob, 15 minutes>", "expires_at": "…", "headers": { "x-ms-blob-type": "BlockBlob", "Content-Type": "video/mp4" } }`.
- **Limits:** a segment is at most 50,000,000 bytes (`413 segment-too-large`) and at most 60,000 ms long (`422 segment-too-long`); `seq` starts at 0 per track, only ever increases, and may skip numbers (see Recovery).
- **Other refusals:**
  - `422 unsupported-format`: a container and codec this track doesn't take;
  - `409 interview-not-started`: the interview has not started yet (uploads are still taken after it ends, so the queue can drain);
  - `403 wrong-interview`: the body names another interview than the token;
  - `422 validation-failed`: a malformed body (unknown track, `seq` below 0 or above 10,000, a `sha256` that isn't 64 hex digits, a `started_at` without a time zone).
- **Retries:** asking again for the same `(interview_id, track, seq)` returns the same `segment_id` with a fresh URL, so retries are safe.
- **`409 segment-acknowledged`:** the segment is already done, so the desktop deletes its local copy.
- **The blob's path** follows §85: `/{org}/interviews/{id}/{screen|camera|audio}/…`.

## Acknowledge — `POST /recordings/segments/{segment_id}/ack`

- **Body:** `{ "sha256": "<hex>" }`.
- **What the server does:** reads the blob, and checks its size and SHA-256 against what was declared.
- **`200`:** `{ "status": "acknowledged" }`. Now, and only now, the desktop deletes its local copy.
- **Errors:**
  - `422 hash-mismatch`: upload again, with a new URL from the call above. It also answers a body hash other than the declared one, and a blob bigger than the declared size (which is not read);
  - `404 blob-missing`: same;
  - `404 segment-not-found`: no such segment for this token's interview.
- **Acknowledging twice** is harmless: an acknowledged segment answers `200` again.

## Recovery after a crash — `GET /recordings/interviews/{interview_id}/segments`

- **`200`:** `{ "tracks": { "screen-1": { "acknowledged_through": 16, "missing": [9] }, "camera": { … } } }`.
  - `acknowledged_through` is the highest acknowledged `seq`, or `null` when nothing is acknowledged yet.
  - `missing` lists every `seq` below it that is not acknowledged, including numbers the desktop skipped and never asked for.
  - Every track the interview records is listed, with `null` and `[]` until its first segment.
- **What the desktop does:** uploads whatever it still holds that isn't acknowledged, for example at its next launch after a power loss. A number it no longer holds stays in `missing` as a gap.
- **Wrong interview:** a token for another interview is `403 wrong-interview`.

## Status

- **Events:** the server publishes `RECORDING_STATUS` (§91) from upload continuity.
- **Gaps:** a gap longer than the policy allows raises `SCREEN_CAPTURE_STOPPED` or `TELEMETRY_GAP`, with no action from the desktop.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane D. Added `expires_at` to the upload-URL answer, and the limits: 50 MB and 60 s per segment, `seq` from 0 per track. A track name the interview doesn't record (for example `camera` when the template records no camera) is `422 track-not-recorded`.
- 2026-10-11: settled with the desktop recording client (lane B) and built by lane D (D2):
  - the 50 MB limit is **50,000,000 bytes**, and the 60 s limit is 60,000 ms (`422 segment-too-long`);
  - `seq` only ever increases per track but **may skip numbers** (a pause over 10 s, or the MediaRecorder fallback after an early stop): a later `seq` is accepted, skipped numbers are listed in the recovery listing's `missing` (they may still arrive, for example from a backlog after a crash) and are reported in a `recording.gap` event of kind `missing` only when the track is assembled after the interview, and a stall is raised once a track is silent for longer than the interview's policy allows (20 s strict, 30 s standard, 60 s basic, 120 s off);
  - in the recovery listing, `acknowledged_through` is **`null`** for a track with nothing acknowledged yet (the highest acknowledged `seq` otherwise), and `missing` is every unacknowledged number below it;
  - the upload-URL request needs **no `Idempotency-Key`**: retries are idempotent through the `(interview, track, seq)` uniqueness;
  - error codes the first draft left unnamed: `422 unsupported-format`, `409 interview-not-started`, `403 wrong-interview`, `404 segment-not-found`, `422 validation-failed` (the API's usual body validation); an acknowledgement for a blob larger than declared is `422 hash-mismatch`;
  - the camera and the mic take `webm` with `vp8` or `opus` and `mp4` with `h264` or `aac`, as the draft words it (the server does not tie a codec to a track beyond that); screens take `mp4` with `h264`.
- 2026-10-11, after review (D2): `recording.gap` is `stalled` while an interview runs, and `missing` or `corrupt` once its track is assembled; it is never raised for numbers that a backlog can still bring.
