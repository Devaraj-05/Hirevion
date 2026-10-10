import type { Format, WebviewTrack } from "./formats";
import type { SegmentSink } from "./native";
import type { SegmentPlanner, ServerTime } from "./timing";

/** What every track recorder shares. */
export interface RecordingContext {
  time: ServerTime;
  /** One set of 10-second windows for every track, so camera and mic seqs line up. */
  planner: SegmentPlanner;
  sink: SegmentSink;
  frameRate: number;
  videoBitrate: number;
  audioBitrate: number;
  onError: (track: WebviewTrack, message: string) => void;
}

/** What one track recorded. */
export interface TrackReport {
  track: WebviewTrack;
  mode: "webcodecs" | "media-recorder";
  format: Format;
  segments: number;
  bytes: number;
  /** Frames dropped because the encoder fell behind, or chunks that didn't fit a file. */
  dropped: number;
  errors: string[];
}

/** A recorder for one track. */
export interface TrackRecorder {
  readonly track: WebviewTrack;
  /** Stops capture and delivers the last segment. */
  stop(): Promise<TrackReport>;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
