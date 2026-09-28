/** Events per second over a sliding window. */
export class FpsMeter {
  private readonly ticks: number[] = [];

  constructor(private readonly windowMs = 1_000) {}

  tick(nowMs: number): void {
    this.ticks.push(nowMs);
    this.trim(nowMs);
  }

  fps(nowMs: number): number {
    this.trim(nowMs);
    return (this.ticks.length * 1_000) / this.windowMs;
  }

  private trim(nowMs: number): void {
    while ((this.ticks[0] ?? Number.POSITIVE_INFINITY) < nowMs - this.windowMs) {
      this.ticks.shift();
    }
  }
}

export interface Summary {
  count: number;
  p50: number;
  p95: number;
  max: number;
}

/** p50, p95 (linear interpolation, like the Python and Rust helpers) and the maximum. */
export function summarize(values: readonly number[]): Summary | null {
  if (values.length === 0) {
    return null;
  }
  const sorted = [...values].sort((a, b) => a - b);
  return {
    count: sorted.length,
    p50: percentile(sorted, 50),
    p95: percentile(sorted, 95),
    max: sorted[sorted.length - 1] ?? 0,
  };
}

function percentile(sorted: readonly number[], pct: number): number {
  const rank = ((sorted.length - 1) * pct) / 100;
  const low = sorted[Math.floor(rank)] ?? 0;
  const high = sorted[Math.ceil(rank)] ?? low;
  return low + (high - low) * (rank - Math.floor(rank));
}
