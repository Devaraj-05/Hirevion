// The driver wrapper must never leave tauri-driver (and msedgedriver, and the app) running on its
// port, whichever way the run ends: success, a failing test, a driver that won't start, one that
// never becomes ready, or one that dies on its own.
import { describe, expect, it } from "vitest";
import { withDriver } from "./driver.mjs";

const SLEEPER = ["-e", "setInterval(() => {}, 1000)"];

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function gone(pid) {
  for (let attempt = 0; attempt < 50; attempt++) {
    if (!alive(pid)) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

const ready = async () => true;

describe("withDriver", () => {
  it("returns what the run returns and stops the driver afterwards", async () => {
    let pid = 0;
    const value = await withDriver(
      { command: process.execPath, args: SLEEPER, ready, onSpawn: (child) => (pid = child.pid) },
      async (child) => {
        expect(alive(child.pid)).toBe(true);
        return 42;
      },
    );
    expect(value).toBe(42);
    expect(await gone(pid)).toBe(true);
  });

  it("stops the driver when the run throws", async () => {
    let pid = 0;
    await expect(
      withDriver(
        { command: process.execPath, args: SLEEPER, ready, onSpawn: (child) => (pid = child.pid) },
        async () => {
          throw new Error("the test failed");
        },
      ),
    ).rejects.toThrow("the test failed");
    expect(await gone(pid)).toBe(true);
  });

  it("stops a driver that never becomes ready, and says so", async () => {
    let pid = 0;
    await expect(
      withDriver(
        {
          command: process.execPath,
          args: SLEEPER,
          ready: async () => false,
          timeoutMs: 600,
          onSpawn: (child) => (pid = child.pid),
        },
        async () => 0,
      ),
    ).rejects.toThrow(/didn't become ready/);
    expect(await gone(pid)).toBe(true);
  });

  it("reports a driver that can't be started instead of hanging", async () => {
    await expect(
      withDriver(
        { command: "hirevion-no-such-driver", args: [], ready: async () => false },
        async () => 0,
      ),
    ).rejects.toThrow(/couldn't start/);
  });

  it("reports a driver that dies on its own", async () => {
    await expect(
      withDriver(
        {
          command: process.execPath,
          args: ["-e", "process.exit(3)"],
          ready: async () => false,
          timeoutMs: 5000,
        },
        async () => 0,
      ),
    ).rejects.toThrow(/exited with code 3/);
  });
});
