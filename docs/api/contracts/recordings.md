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
- **Limits:** a segment is at most 50 MB (`413 segment-too-large`) and at most 60 s long; `seq` starts at 0 per track.
- **Retries:** asking again for the same `(interview_id, track, seq)` returns the same `segment_id` with a fresh URL, so retries are safe.
- **`409 segment-acknowledged`:** the segment is already done, so the desktop deletes its local copy.
- **The blob's path** follows §85: `/{org}/interviews/{id}/{screen|camera|audio}/…`.

## Acknowledge — `POST /recordings/segments/{segment_id}/ack`

- **Body:** `{ "sha256": "<hex>" }`.
- **What the server does:** reads the blob, and checks its size and SHA-256 against what was declared.
- **`200`:** `{ "status": "acknowledged" }`. Now, and only now, the desktop deletes its local copy.
- **Errors:**
  - `422 hash-mismatch`: upload again, with a new URL from the call above;
  - `404 blob-missing`: same.

## Recovery after a crash — `GET /recordings/interviews/{interview_id}/segments`

- **`200`:** `{ "tracks": { "screen-1": { "acknowledged_through": 16, "missing": [9] }, "camera": { … } } }`.
- **What the desktop does:** uploads whatever it still holds that isn't acknowledged, for example at its next launch after a power loss.

## Status

- **Events:** the server publishes `RECORDING_STATUS` (§91) from upload continuity.
- **Gaps:** a gap longer than the policy allows raises `SCREEN_CAPTURE_STOPPED` or `TELEMETRY_GAP`, with no action from the desktop.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane D. Added `expires_at` to the upload-URL answer, and the limits: 50 MB and 60 s per segment, `seq` from 0 per track. A track name the interview doesn't record (for example `camera` when the template records no camera) is `422 track-not-recorded`.
