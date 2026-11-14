import { describe, expect, it, vi } from "vitest";
import { fitFrame, withTimeout } from "./frame";

describe("the size of an evidence picture", () => {
  it("keeps the shape, scales down to 1280x720 at most, and never up", () => {
    expect(fitFrame(1920, 1080)).toEqual({ width: 1280, height: 720 });
    expect(fitFrame(640, 480)).toEqual({ width: 640, height: 480 });
    expect(fitFrame(1080, 1920)).toEqual({ width: 405, height: 720 });
    expect(fitFrame(0, 0)).toEqual({ width: 0, height: 0 });
  });
});

describe("a camera grab that never finishes", () => {
  it("is given up after its time, so nothing is left running", async () => {
    vi.useFakeTimers();
    try {
      const never = new Promise<Uint8Array>(() => undefined);
      const result = withTimeout(never, 5_000).catch((error: Error) => error.message);
      await vi.advanceTimersByTimeAsync(5_000);
      expect(await result).toBe("the camera gave no frame in time");
    } finally {
      vi.useRealTimers();
    }
  });

  it("passes on a frame that comes in time", async () => {
    const frame = new Uint8Array([0xff, 0xd8, 0xff]);
    await expect(withTimeout(Promise.resolve(frame), 5_000)).resolves.toBe(frame);
  });
});
