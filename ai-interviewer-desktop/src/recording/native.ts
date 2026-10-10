import { invoke } from "@tauri-apps/api/core";
import { type Codec, type Container, isAllowed, type WebviewTrack } from "./formats";
import { MAX_SEGMENT_MS } from "./timing";

/**
 * The Rust side of camera and microphone recording (wired in SP-08b):
 *
 * - `recording_clock` → `{ server_offset_ms }`: server time minus this PC's time, from the
 *   API client's `GET /time` sync.
 * - `recording_store_segment` takes one finished segment as raw bytes, described by the
 *   headers below. Rust encrypts it into the segment store for the interview being recorded
 *   (the webview never names the interview) and wakes the uploader.
 */

export interface SegmentMeta {
  track: WebviewTrack;
  /** From 0 per track, always increasing. */
  seq: number;
  /** The first sample, in server milliseconds since the Unix epoch. */
  startedAtMs: number;
  durationMs: number;
  container: Container;
  codec: Codec;
}

export interface RecordingClock {
  server_offset_ms: number;
}

export interface StoredSegment {
  track: string;
  seq: number;
  bytes: number;
  state: string;
}

/** Hands a finished segment to its destination (Rust, or a test double). */
export type SegmentSink = (meta: SegmentMeta, bytes: Uint8Array) => Promise<void>;

/** The headers `recording_store_segment` reads (see `hv_segment_store::webview`). */
export function segmentHeaders(meta: SegmentMeta): Record<string, string> {
  if (!Number.isSafeInteger(meta.seq) || meta.seq < 0) {
    throw new Error(`bad seq ${meta.seq}`);
  }
  if (!Number.isFinite(meta.startedAtMs) || !Number.isFinite(meta.durationMs)) {
    throw new Error("segment timing must be finite");
  }
  if (!isAllowed(meta.track, meta.container, meta.codec)) {
    throw new Error(`${meta.track} can't be ${meta.container}/${meta.codec}`);
  }
  const durationMs = Math.min(MAX_SEGMENT_MS, Math.max(1, Math.round(meta.durationMs)));
  return {
    "x-hv-track": meta.track,
    "x-hv-seq": String(meta.seq),
    "x-hv-started-at-ms": String(Math.round(meta.startedAtMs)),
    "x-hv-duration-ms": String(durationMs),
    "x-hv-container": meta.container,
    "x-hv-codec": meta.codec,
  };
}

export const recordingCommands = {
  clock: () => invoke<RecordingClock>("recording_clock"),
  storeSegment: (meta: SegmentMeta, bytes: Uint8Array) =>
    invoke<StoredSegment>("recording_store_segment", bytes, { headers: segmentHeaders(meta) }),
};

/** The default sink: Rust's encrypted segment store. */
export const storeInRust: SegmentSink = async (meta, bytes) => {
  await recordingCommands.storeSegment(meta, bytes);
};
