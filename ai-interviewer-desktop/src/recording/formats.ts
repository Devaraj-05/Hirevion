/** The webview's tracks and the formats `docs/api/contracts/recordings.md` allows for them. */

export type WebviewTrack = "camera" | "mic";
export type Container = "mp4" | "webm";
export type Codec = "h264" | "vp8" | "opus" | "aac";

export interface Format {
  container: Container;
  codec: Codec;
}

export interface RecorderFormat extends Format {
  /** The `MediaRecorder` MIME type that produces it. */
  recorderMime: string;
}

export const CAMERA_H264: Format = { container: "mp4", codec: "h264" };
export const CAMERA_VP8: Format = { container: "webm", codec: "vp8" };
export const MIC_OPUS: Format = { container: "webm", codec: "opus" };

/** Camera: MP4/H.264 or WebM/VP8; microphone: WebM/Opus or MP4/AAC. */
export function isAllowed(track: WebviewTrack, container: Container, codec: Codec): boolean {
  if (track === "camera") {
    return (container === "mp4" && codec === "h264") || (container === "webm" && codec === "vp8");
  }
  return (container === "webm" && codec === "opus") || (container === "mp4" && codec === "aac");
}

/** H.264 (hardware first) when WebCodecs can encode it, VP8 otherwise. */
export function chooseCameraFormat(h264Supported: boolean): Format {
  return h264Supported ? CAMERA_H264 : CAMERA_VP8;
}

const RECORDER_CANDIDATES: Record<WebviewTrack, RecorderFormat[]> = {
  camera: [
    { container: "webm", codec: "vp8", recorderMime: "video/webm;codecs=vp8" },
    { container: "mp4", codec: "h264", recorderMime: "video/mp4;codecs=avc1" },
  ],
  mic: [
    { container: "webm", codec: "opus", recorderMime: "audio/webm;codecs=opus" },
    { container: "mp4", codec: "aac", recorderMime: "audio/mp4;codecs=mp4a.40.2" },
  ],
};

/** The first `MediaRecorder` type the contract accepts and the browser supports. */
export function chooseRecorderFormat(
  track: WebviewTrack,
  isTypeSupported: (mime: string) => boolean,
): RecorderFormat | null {
  return RECORDER_CANDIDATES[track].find((format) => isTypeSupported(format.recorderMime)) ?? null;
}
