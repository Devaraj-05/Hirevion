/**
 * Sound levels for the orb (C8-12): how loud the interviewer or the candidate is right now, read
 * from a Web Audio `AnalyserNode`'s time-domain bytes (silence is 128), smoothed so the orb
 * moves like a physical thing, never jitters, and never overshoots.
 */

/** Loudness from 0 (silence) to 1, from unsigned 8-bit samples centred on 128. */
export function level(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let n = 0; n < samples.length; n += 1) {
    const value = ((samples[n] ?? 128) - 128) / 128;
    sum += value * value;
  }
  const rms = Math.sqrt(sum / samples.length);
  // Below the floor is room noise; speech sits around 0.05–0.3 RMS, so the square root lifts a
  // normal voice enough to move the orb visibly.
  const above = Math.max(0, rms - NOISE_FLOOR) / (FULL_SCALE - NOISE_FLOOR);
  return Math.min(1, Math.sqrt(above));
}

const NOISE_FLOOR = 0.02;
const FULL_SCALE = 0.35;

/** Critically damped following: `current` moves toward `target`, `tauMs` sets how quickly. */
export function follow(current: number, target: number, elapsedMs: number, tauMs = 90): number {
  if (current === target) return current;
  return current + (target - current) * (1 - Math.exp(-Math.max(0, elapsedMs) / tauMs));
}

/** Speech starts above `OPEN` and ends below `CLOSE`, so a pause between words doesn't flicker. */
export const OPEN = 0.15;
export const CLOSE = 0.05;

export function voiced(current: number, wasVoiced: boolean): boolean {
  return wasVoiced ? current >= CLOSE : current >= OPEN;
}

export interface Scales {
  core: number;
  rings: [number, number, number];
  strip: number;
}

/**
 * What the level moves (perf, 2026-11-24): the sphere a little, its three rings more the farther
 * out they are, and the waveform strip as one piece. Set straight on each element's transform:
 * a CSS variable on the card made the browser restyle the transcript every frame.
 */
export function scales(value: number): Scales {
  const round = (n: number) => Math.round(n * 1000) / 1000;
  return {
    core: round(1 + value * 0.04),
    rings: [round(1 + value * 0.05), round(1 + value * 0.09), round(1 + value * 0.14)],
    strip: round(0.6 + value * 0.4),
  };
}
