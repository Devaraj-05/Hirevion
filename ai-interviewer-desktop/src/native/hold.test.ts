import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { switchHolder } from "./hold";

describe("switchHolder", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("enters once and leaves after the last holder lets go", () => {
    const set = vi.fn(async (_on: boolean) => undefined);
    const hold = switchHolder(set);
    const release = hold();
    expect(set.mock.calls).toEqual([[true]]);
    release();
    vi.runAllTimers();
    expect(set.mock.calls).toEqual([[true], [false]]);
  });

  it("doesn't flicker when a holder lets go and takes hold again at once (StrictMode)", () => {
    // 2026-11-25: the interview's effect ran mount, cleanup, mount, so the window went
    // fullscreen, windowed and fullscreen again as the interview opened.
    const set = vi.fn(async (_on: boolean) => undefined);
    const hold = switchHolder(set);
    hold()();
    hold();
    vi.runAllTimers();
    expect(set.mock.calls).toEqual([[true]]);
  });

  it("ignores a second release from the same holder", () => {
    const set = vi.fn(async (_on: boolean) => undefined);
    const hold = switchHolder(set);
    const first = hold();
    hold();
    first();
    first();
    vi.runAllTimers();
    expect(set.mock.calls).toEqual([[true]]);
  });

  it("survives a window that refuses", () => {
    const set = vi.fn(async (_on: boolean) => {
      throw new Error("refused");
    });
    const hold = switchHolder(set);
    expect(() => hold()()).not.toThrow();
    vi.runAllTimers();
  });
});
