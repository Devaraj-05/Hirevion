import type { RecordingContext, TrackRecorder, TrackReport } from "./context";
import type { WebviewTrack } from "./formats";
import { RotatingRecorder } from "./media-recorder";
import { recordingCommands, type SegmentSink, storeInRust } from "./native";
import { SEGMENT_MS, SegmentPlanner, ServerTime } from "./timing";
import { CameraTrack, MicTrack, webCodecsAvailable } from "./webcodecs";

export interface RecordingOptions {
  /** Where finished segments go; Rust's encrypted segment store by default. */
  sink?: SegmentSink;
  /** Server time minus local time; asked from Rust (`recording_clock`) when absent. */
  serverOffsetMs?: number;
  frameRate?: number;
  videoBitrate?: number;
  audioBitrate?: number;
  /** Use MediaRecorder even when WebCodecs is available. */
  forceMediaRecorder?: boolean;
  onError?: (track: WebviewTrack, message: string) => void;
}

/** A running camera and microphone recording. */
export interface MediaRecording {
  readonly mode: "webcodecs" | "media-recorder";
  readonly tracks: WebviewTrack[];
  /** The server's clock moved (a new `GET /time` sync in Rust). */
  setServerOffset(offsetMs: number): void;
  /** Stops one track, e.g. after `track-not-recorded`. */
  stopTrack(track: WebviewTrack): Promise<TrackReport | null>;
  /** Stops everything and delivers the last segments. */
  stop(): Promise<TrackReport[]>;
}

const DEFAULTS = {
  frameRate: 15,
  videoBitrate: 1_000_000,
  audioBitrate: 32_000,
};

/**
 * Records the stream's camera and microphone into 10-second segments (PRD §49–51): WebCodecs
 * and Mediabunny when available, MediaRecorder otherwise. Each segment goes to `sink` with its
 * track, seq and server-time start; the camera and mic share one set of windows.
 */
export async function startMediaRecording(
  stream: MediaStream,
  options: RecordingOptions = {},
): Promise<MediaRecording> {
  const serverOffsetMs =
    options.serverOffsetMs ?? (await recordingCommands.clock()).server_offset_ms;
  const time = ServerTime.fromPerformance(serverOffsetMs);
  const ctx: RecordingContext = {
    time,
    planner: new SegmentPlanner(time.nowMs(), SEGMENT_MS),
    sink: options.sink ?? storeInRust,
    frameRate: options.frameRate ?? DEFAULTS.frameRate,
    videoBitrate: options.videoBitrate ?? DEFAULTS.videoBitrate,
    audioBitrate: options.audioBitrate ?? DEFAULTS.audioBitrate,
    onError: options.onError ?? (() => {}),
  };
  const mode = !options.forceMediaRecorder && webCodecsAvailable() ? "webcodecs" : "media-recorder";
  const recorders = new Map<WebviewTrack, TrackRecorder>();
  const camera = stream.getVideoTracks()[0];
  const mic = stream.getAudioTracks()[0];
  try {
    if (camera) {
      recorders.set(
        "camera",
        mode === "webcodecs"
          ? await CameraTrack.start(camera, ctx)
          : RotatingRecorder.start("camera", camera, ctx),
      );
    }
    if (mic) {
      recorders.set(
        "mic",
        mode === "webcodecs"
          ? await MicTrack.start(mic, ctx)
          : RotatingRecorder.start("mic", mic, ctx),
      );
    }
  } catch (error) {
    await Promise.allSettled([...recorders.values()].map((recorder) => recorder.stop()));
    throw error;
  }

  return {
    mode,
    tracks: [...recorders.keys()],
    setServerOffset: (offsetMs) => time.setOffset(offsetMs),
    stopTrack: async (track) => {
      const recorder = recorders.get(track);
      if (!recorder) {
        return null;
      }
      recorders.delete(track);
      return recorder.stop();
    },
    stop: async () => {
      const all = [...recorders.values()];
      recorders.clear();
      return Promise.all(all.map((recorder) => recorder.stop()));
    },
  };
}
