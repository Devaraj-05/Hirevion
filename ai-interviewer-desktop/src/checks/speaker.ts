import type { CheckResult } from "./types";

export const TEST_TONE_HZ = 1_000;
export const TEST_TONE_MS = 1_000;

export interface TestToneOptions {
  frequency?: number;
  durationMs?: number;
  /** Linear gain, 0 to 1. Kept well below full scale so the tone isn't harsh. */
  volume?: number;
}

/** Fade in and out over this long, so the tone starts and stops without a click. */
const FADE_SECONDS = 0.02;

/**
 * Plays a sine tone (1 kHz for 1 s by default) through the default output and resolves when it
 * ends. The result comes from the candidate afterwards: see `speakerResult`.
 */
export async function playTestTone(options: TestToneOptions = {}): Promise<void> {
  const frequency = options.frequency ?? TEST_TONE_HZ;
  const seconds = (options.durationMs ?? TEST_TONE_MS) / 1_000;
  const volume = options.volume ?? 0.25;
  const context = new AudioContext();
  try {
    if (context.state === "suspended") {
      await context.resume();
    }
    const oscillator = new OscillatorNode(context, { type: "sine", frequency });
    const gain = new GainNode(context, { gain: 0 });
    const start = context.currentTime;
    const end = start + seconds;
    const fade = Math.min(FADE_SECONDS, seconds / 2);
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(volume, start + fade);
    gain.gain.setValueAtTime(volume, end - fade);
    gain.gain.linearRampToValueAtTime(0, end);
    oscillator.connect(gain).connect(context.destination);
    const ended = new Promise<void>((resolve) => {
      oscillator.addEventListener("ended", () => resolve(), { once: true });
    });
    oscillator.start(start);
    oscillator.stop(end);
    await ended;
  } finally {
    await context.close();
  }
}

/** The speaker check, from the candidate's answer to "Did you hear the tone?". */
export function speakerResult(confirmed: boolean): CheckResult {
  if (confirmed) {
    return { check: "speaker", status: "pass", value: "test tone heard" };
  }
  return {
    check: "speaker",
    status: "fail",
    value: "test tone not heard",
    detail:
      "Check the volume and that the right speakers or headphones are selected in Windows, then play the tone again.",
  };
}
