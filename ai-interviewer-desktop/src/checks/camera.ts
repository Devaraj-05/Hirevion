import { mediaFailure } from "./errors";
import { cameraResult } from "./thresholds";
import type { CheckResult } from "./types";

export interface CameraCheckOptions {
  /** A camera from `enumerateDevices`; the default camera otherwise. */
  deviceId?: string;
}

/**
 * Opens the camera at up to 1280x720 and 30 fps, reads the mode it settled on, and stops it.
 * Judged by `cameraResult`.
 */
export async function checkCamera(options: CameraCheckOptions = {}): Promise<CheckResult> {
  const video: MediaTrackConstraints = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 30 },
  };
  if (options.deviceId) {
    video.deviceId = { exact: options.deviceId };
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
  } catch (error) {
    return mediaFailure("camera", error);
  }
  try {
    const track = stream.getVideoTracks()[0];
    if (!track) {
      return mediaFailure("camera", new DOMException("No video track", "NotFoundError"));
    }
    const settings = track.getSettings();
    return cameraResult({
      label: track.label,
      width: settings.width ?? 0,
      height: settings.height ?? 0,
      frameRate: settings.frameRate ?? 0,
    });
  } finally {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  }
}
