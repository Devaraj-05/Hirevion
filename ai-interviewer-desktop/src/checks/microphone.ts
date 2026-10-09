import { mediaFailure } from "./errors";
import { MICROPHONE_SAMPLE_MS, microphoneResult, peakDbfs } from "./thresholds";
import type { CheckResult } from "./types";

export interface MicrophoneCheckOptions {
  /** A microphone from `enumerateDevices`; the default microphone otherwise. */
  deviceId?: string;
  durationMs?: number;
  /** Each block's peak in dBFS (about every 40 ms), for a level meter. */
  onLevel?: (peakDbfs: number) => void;
}

/** 2048 samples are about 43 ms at 48 kHz, so reading every 40 ms misses nothing. */
const FFT_SIZE = 2_048;
const READ_INTERVAL_MS = 40;

/**
 * Listens to the microphone for 3 s (by default) while the candidate speaks, and judges the
 * loudest moment with `microphoneResult`. The constraints are the browser defaults, the same
 * processing (echo cancellation, noise suppression, gain) the interview itself uses.
 */
export async function checkMicrophone(options: MicrophoneCheckOptions = {}): Promise<CheckResult> {
  const audio: MediaTrackConstraints | boolean = options.deviceId
    ? { deviceId: { exact: options.deviceId } }
    : true;
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio, video: false });
  } catch (error) {
    return mediaFailure("microphone", error);
  }
  let context: AudioContext | undefined;
  try {
    context = new AudioContext();
    if (context.state === "suspended") {
      await context.resume();
    }
    const analyser = new AnalyserNode(context, { fftSize: FFT_SIZE });
    context.createMediaStreamSource(stream).connect(analyser);
    const peak = await listen(
      analyser,
      options.durationMs ?? MICROPHONE_SAMPLE_MS,
      options.onLevel,
    );
    return microphoneResult(peak);
  } catch (error) {
    return mediaFailure("microphone", error);
  } finally {
    for (const track of stream.getTracks()) {
      track.stop();
    }
    await context?.close();
  }
}

/** The highest block peak (dBFS) seen over `durationMs`. */
function listen(
  analyser: AnalyserNode,
  durationMs: number,
  onLevel: ((peakDbfs: number) => void) | undefined,
): Promise<number> {
  const samples = new Float32Array(analyser.fftSize);
  let peak = Number.NEGATIVE_INFINITY;
  const started = performance.now();
  return new Promise((resolve) => {
    const timer = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      const level = peakDbfs(samples);
      peak = Math.max(peak, level);
      onLevel?.(level);
      if (performance.now() - started >= durationMs) {
        clearInterval(timer);
        resolve(peak);
      }
    }, READ_INTERVAL_MS);
  });
}
