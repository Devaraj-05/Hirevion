import { describe, expect, it } from "vitest";
import { segmentHeaders } from "./native";

describe("segmentHeaders", () => {
  it("describes a segment in the headers Rust reads", () => {
    expect(
      segmentHeaders({
        track: "camera",
        seq: 4,
        startedAtMs: 1_760_245_400_123.6,
        durationMs: 9_999.6,
        container: "mp4",
        codec: "h264",
      }),
    ).toEqual({
      "x-hv-track": "camera",
      "x-hv-seq": "4",
      "x-hv-started-at-ms": "1760245400124",
      "x-hv-duration-ms": "10000",
      "x-hv-container": "mp4",
      "x-hv-codec": "h264",
    });
  });

  it("keeps durations within the contract's 1 ms to 60 s", () => {
    const base = {
      track: "mic",
      seq: 0,
      startedAtMs: 1,
      container: "webm",
      codec: "opus",
    } as const;
    expect(segmentHeaders({ ...base, durationMs: 0.2 })["x-hv-duration-ms"]).toBe("1");
    expect(segmentHeaders({ ...base, durationMs: 75_000 })["x-hv-duration-ms"]).toBe("60000");
  });

  it("refuses what the contract doesn't allow", () => {
    const base = {
      track: "camera",
      seq: 0,
      startedAtMs: 1,
      durationMs: 10_000,
      container: "mp4",
      codec: "h264",
    } as const;
    expect(() => segmentHeaders({ ...base, seq: -1 })).toThrow();
    expect(() => segmentHeaders({ ...base, seq: 1.5 })).toThrow();
    expect(() => segmentHeaders({ ...base, codec: "opus" })).toThrow();
    expect(() => segmentHeaders({ ...base, startedAtMs: Number.NaN })).toThrow();
  });
});
