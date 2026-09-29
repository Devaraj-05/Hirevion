import { describe, expect, it } from "vitest";
import { createApiClient } from "./client";
import { estimateClockOffset, syncClock } from "./clock";

describe("estimateClockOffset", () => {
  it("uses the NTP formula on the fastest round trip", () => {
    const estimate = estimateClockOffset([
      { t0: 0, t1: 900, t2: 950, t3: 400 },
      { t0: 1000, t1: 1600, t2: 1602, t3: 1010 },
    ]);
    // offset = ((1600 - 1000) + (1602 - 1010)) / 2; rtt = (1010 - 1000) - (1602 - 1600)
    expect(estimate).toEqual({ offsetMs: 596, rttMs: 8 });
  });

  it("needs at least one sample", () => {
    expect(() => estimateClockOffset([])).toThrow(/sample/);
  });
});

describe("syncClock", () => {
  it("samples the server clock the given number of times", async () => {
    const urls: string[] = [];
    const client = createApiClient({
      baseUrl: "https://api.hirevion.localhost",
      fetch: async (request) => {
        urls.push(request.url);
        return Response.json({ received_at_ms: 1600, sent_at_ms: 1602 });
      },
    });
    const ticks = [1000, 1010, 1000, 1030, 1000, 1050];
    const estimate = await syncClock(client, 3, () => ticks.shift() ?? 0);

    expect(urls).toEqual(Array(3).fill("https://api.hirevion.localhost/api/v1/time"));
    expect(estimate).toEqual({ offsetMs: 596, rttMs: 8 });
  });
});
