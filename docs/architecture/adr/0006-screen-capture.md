# ADR-0006: Screen capture and H.264 segment recording

- **Status:** Accepted
- **Date:** 2026-09-28
- **Sub-project:** SP-00d (spike 2)

## Context

The desktop app must record every display for the whole interview (PRD §50–51). Recordings are cut into 10-second segments that are encrypted, uploaded and acknowledged one by one. The recording must stay light enough for a candidate's ordinary laptop, and small enough to upload over Indian home broadband while LiveKit also streams live audio and video.

Measured on the development PC: Intel Core i5-8350U (4 cores, 8 threads), Intel UHD Graphics 620, one 1920×1080 display, Windows 11 25H2. Numbers come from `crates/recorder/examples/capture_bench.rs`, 60 seconds per run, on a repeatable screen: `examples/activity.html`, a simulated coding interview that types code, scrolls, prints test output and animates. CPU is the benchmark process's share of all 8 logical processors.

| Setting (1080p, 15 fps, 10 s segments) | Busy coding screen | Still screen | CPU | Peak memory |
|---|---|---|---|---|
| Quick Sync, VBR 1.5 Mbps, keyframe every 2 s | 3.8 MB/min | 2.6 MB/min | 1.1 % | 200 MB |
| Quick Sync, VBR 0.8 Mbps, keyframe every 2 s | 2.2 MB/min | — | 1.0 % | 200 MB |
| Quick Sync, constant quality 65, keyframe every 2 s | 2.4 MB/min | — | 1.2 % | 208 MB |
| Quick Sync, constant quality 50, keyframe every 2 s | 1.8 MB/min | 1.3 MB/min | 0.9 % | 208 MB |
| Quick Sync, constant quality 50, one keyframe per segment | not measured cleanly (see below) | **0.4 MB/min** | 0.7 % | 216 MB |
| Microsoft software encoder, VBR 1.5 Mbps | 4.7 MB/min | — | 4.4 % | 469 MB |

Also observed:

- **Every run:**
  - no late ticks;
  - encode-submit time p95 under 2.5 ms;
  - 6 of 6 segments complete MP4s.
- **Segment format** (checked with ffprobe):
  - H.264 Main, level 4.0, BT.709 limited range;
  - exactly 150 frames and 10.0 s per segment.
- **Joining segments:** the concat demuxer joins them with `-c copy` into one file (59.3 s, 890 frames) that decodes without errors.
- **Text quality:** 15 px code text is fully legible at quality 50.
- **Content matters:** a real desktop with a video playing reached 3.3 MB for one 10-second segment (2.7 Mbps), and an ordinary working desktop at VBR 1.5 Mbps reached 11 MB/min. The clean busy-screen measurement with one keyframe per segment was spoiled by a video on screen; the estimate from the keyframe cost below is 0.8–1.0 MB/min.
- **Opening an encoder is slow:** about 345 ms for Quick Sync. Doing it at each segment boundary froze capture and caused late ticks.
- **Media Foundation's MPEG-4 sink rejects byte streams wrapped around an `HGLOBAL` `IStream`:** `BeginWriting` fails with E_INVALIDARG. A WinRT `InMemoryRandomAccessStream` (through `MFCreateMFByteStreamOnStreamEx`) works with both the hardware and software encoders.

## Decision

- **Capture:**
  - Windows Graphics Capture, one session per display, polled for the newest frame at a fixed 15 fps.
  - An unchanged screen repeats the last frame.
  - `MinUpdateInterval` is set to the frame interval (Windows 11 24H2+).
  - The cursor is captured.
  - The yellow capture border stays by default; it can only be removed on Windows 11, and it tells the candidate that recording is on.
- **Conversion:**
  - The D3D11 video processor turns BGRA into NV12 on the GPU (BT.709, limited range) and scales down to fit 1920×1080. There are no CPU copies.
  - A ring of 8 NV12 textures lets the encoder hold frames in flight.
- **Encoding:**
  - A Media Foundation Sink Writer, hardware encoder first and Microsoft's software encoder as the fallback.
  - H.264 Main at **constant quality 50** with **one keyframe per 10-second segment** (GOP = segment length).
  - Each segment starts with an IDR frame, so every file plays on its own.
- **Memory only:**
  - Segments are written into memory and never touch the disk unencrypted; SP-12 encrypts them before writing.
  - The next segment's writer is opened ahead of time on a helper thread, so rotation takes under 0.1 ms.
  - Finished segments are finalized on a separate thread (40–100 ms) and SHA-256 hashed with Windows CNG.
- **Budget:** under 1.5 % CPU with a hardware encoder and under 5 % in software, against budgets of 5 % and 15 %.

## Consequences

- A 45-minute interview's screen recording is about 20–45 MB with typical content: under 150 kbps of upload on average.
- Constant quality has no upper bit-rate limit: a video playing on screen costs about 2.7 Mbps while it plays. SP-12's uploader must throttle and queue rather than assume a fixed rate.
- With one keyframe per segment, a seek can decode up to 10 s of frames. That is fast with hardware decoding, and the media worker can re-encode for review playback if needed.
- **Follow-ups:**
  - **SP-12:**
    - Measure a clean busy screen with one keyframe per segment.
    - Test with a second monitor.
    - Try a 4-texture ring to cut the ~200 MB working set.
    - Name the software encoder in reports.
  - **SP-11:**
    - Handle display add/remove and resolution changes. Today a resolution change rescales into the original encoder size.
  - **SP-12:** add encryption, the upload queue and the acknowledgement protocol on top of `Recorder`.
