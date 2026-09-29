import type { ApiClient } from "./client";

/** One round trip: t0/t3 are this client's clock, t1/t2 the server's (all Unix ms). */
export interface ClockSample {
  t0: number;
  t1: number;
  t2: number;
  t3: number;
}

export interface ClockEstimate {
  /** Add to the local clock to get server time. */
  offsetMs: number;
  /** Network round trip of the sample the estimate came from. */
  rttMs: number;
}

/** NTP's estimate from the sample with the shortest round trip, the least distorted one. */
export function estimateClockOffset(samples: readonly ClockSample[]): ClockEstimate {
  let best: ClockEstimate | undefined;
  for (const { t0, t1, t2, t3 } of samples) {
    const rttMs = t3 - t0 - (t2 - t1);
    const offsetMs = (t1 - t0 + (t2 - t3)) / 2;
    if (best === undefined || rttMs < best.rttMs) best = { offsetMs, rttMs };
  }
  if (best === undefined) throw new Error("estimateClockOffset needs at least one sample");
  return best;
}

/** Measure this client's offset from the server clock over `rounds` calls to `/time`. */
export async function syncClock(
  client: ApiClient,
  rounds = 5,
  now: () => number = Date.now,
): Promise<ClockEstimate> {
  const samples: ClockSample[] = [];
  for (let round = 0; round < rounds; round++) {
    const t0 = now();
    const { data } = await client.GET("/api/v1/time");
    const t3 = now();
    if (data) samples.push({ t0, t1: data.received_at_ms, t2: data.sent_at_ms, t3 });
  }
  return estimateClockOffset(samples);
}
