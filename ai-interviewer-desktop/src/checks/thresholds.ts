import type { CheckResult } from "./types";

/**
 * The webview's thresholds from the SP-08a plan. Displays, memory and disk are judged in Rust
 * (`hv_system_check::classify`); only the checks that need the webview's media stack are here.
 */

/** A microphone passes when its peak over the sample is above this. */
export const MICROPHONE_PASS_DBFS = -50;
/** How long the microphone is listened to. */
export const MICROPHONE_SAMPLE_MS = 3_000;
export const CAMERA_MIN_WIDTH = 640;
export const CAMERA_MIN_HEIGHT = 480;
export const CAMERA_MIN_FPS = 15;

/** Decibels relative to full scale for a linear amplitude (1 is full scale). Silence is -Infinity. */
export function dbfs(amplitude: number): number {
  const magnitude = Math.abs(amplitude);
  return magnitude === 0 ? Number.NEGATIVE_INFINITY : 20 * Math.log10(magnitude);
}

/** The largest magnitude in a block of samples; 0 for an empty block. */
export function peakAmplitude(samples: ArrayLike<number>): number {
  let peak = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const magnitude = Math.abs(samples[index] ?? 0);
    if (magnitude > peak) {
      peak = magnitude;
    }
  }
  return peak;
}

/** The peak level of a block of samples in dBFS: -Infinity when it is silent. */
export function peakDbfs(samples: ArrayLike<number>): number {
  return dbfs(peakAmplitude(samples));
}

/**
 * Passes when the loudest moment of the sample was above -50 dBFS. The level is judged as it
 * is shown, rounded to a whole decibel.
 */
export function microphoneResult(peakDbfsValue: number): CheckResult {
  if (!Number.isFinite(peakDbfsValue)) {
    return {
      check: "microphone",
      status: "fail",
      value: "no sound",
      detail:
        "The microphone picked up no sound. Check it isn't muted, then speak during the test.",
    };
  }
  const shown = Math.round(peakDbfsValue) || 0;
  const value = `${shown} dBFS peak`;
  if (shown > MICROPHONE_PASS_DBFS) {
    return { check: "microphone", status: "pass", value };
  }
  return {
    check: "microphone",
    status: "fail",
    value,
    detail:
      "The microphone is too quiet. Move closer, check its input volume, then speak during the test.",
  };
}

/** What the camera's track reports once it is running. */
export interface CameraSettings {
  label: string;
  width: number;
  height: number;
  frameRate: number;
}

/**
 * Passes at 640x480 and 15 fps or better. A camera below that still works, so it only warns;
 * the camera is mandatory, so a warning still blocks the interview (see `missingMandatory`).
 */
export function cameraResult(settings: CameraSettings): CheckResult {
  const fps = Math.round(settings.frameRate);
  const label = settings.label.trim() || "Camera";
  const value = `${label} ${settings.width}x${settings.height}@${fps}`;
  const enough =
    settings.width >= CAMERA_MIN_WIDTH &&
    settings.height >= CAMERA_MIN_HEIGHT &&
    fps >= CAMERA_MIN_FPS;
  if (enough) {
    return { check: "camera", status: "pass", value };
  }
  return {
    check: "camera",
    status: "warn",
    value,
    detail: `The camera gives ${settings.width}x${settings.height} at ${fps} fps; the interview needs at least ${CAMERA_MIN_WIDTH}x${CAMERA_MIN_HEIGHT} at ${CAMERA_MIN_FPS} fps. Try another camera or close apps that use it.`,
  };
}

/** The WebView2 runtime's version, from the `Edg/` token every WebView2 user agent carries. */
export function webview2Result(userAgent: string): CheckResult {
  const version = /\bEdg\/(\d+(?:\.\d+){1,3})/.exec(userAgent)?.[1];
  if (version) {
    return { check: "webview2", status: "pass", value: version };
  }
  return {
    check: "webview2",
    status: "warn",
    value: "unknown",
    detail: "The WebView2 runtime version could not be read.",
  };
}
