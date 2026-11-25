import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EndingSteps, endInterview } from "./ending";

const never = () => new Promise<never>(() => undefined);
const LIMITS = { flush: 30, stopServices: 50, complete: 80, disconnect: 20 };

function steps(overrides: Partial<EndingSteps> = {}): EndingSteps & { order: string[] } {
  const order: string[] = [];
  const step = (name: string) => async () => {
    order.push(name);
  };
  return {
    order,
    flush: step("flush"),
    stopServices: step("stopServices"),
    complete: step("complete"),
    disconnect: step("disconnect"),
    ...overrides,
  };
}

describe("endInterview", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("saves, stops, completes and leaves, in that order", async () => {
    const run = steps();
    await endInterview(run, () => undefined, LIMITS);
    expect(run.order).toEqual(["flush", "stopServices", "complete", "disconnect"]);
  });

  it("ends even when the recording never stops (2026-11-25: End Interview did nothing)", async () => {
    const run = steps({ stopServices: never });
    const failed = vi.fn();
    const done = endInterview(run, failed, LIMITS);
    await vi.advanceTimersByTimeAsync(LIMITS.flush + LIMITS.stopServices);
    await done;
    expect(run.order).toEqual(["flush", "complete", "disconnect"]);
    expect(failed).not.toHaveBeenCalled();
  });

  it("reports a refused or stuck completion and still leaves the room", async () => {
    const refused = new Error("refused");
    const run = steps({
      complete: async () => {
        throw refused;
      },
    });
    const failed = vi.fn();
    await endInterview(run, failed, LIMITS);
    expect(failed).toHaveBeenCalledWith(refused);
    expect(run.order).toContain("disconnect");

    const stuck = steps({ complete: never });
    const failedToo = vi.fn();
    const done = endInterview(stuck, failedToo, LIMITS);
    await vi.advanceTimersByTimeAsync(LIMITS.complete + LIMITS.disconnect);
    await done;
    expect(failedToo).toHaveBeenCalledOnce();
    expect(stuck.order).toContain("disconnect");
  });
});
