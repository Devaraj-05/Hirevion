import { describe, expect, it } from "vitest";
import { lockLandscape, turnAdvice } from "./orientation";

function page(options: { fullscreen?: boolean; lock?: (to: string) => Promise<void> } = {}) {
  const calls: string[] = [];
  const doc = {
    fullscreenElement: options.fullscreen ? ({} as Element) : null,
    documentElement: {
      requestFullscreen: async () => {
        calls.push("fullscreen");
      },
    },
    exitFullscreen: async () => {
      calls.push("exit fullscreen");
    },
  };
  const lock =
    options.lock ??
    (async (to: string) => {
      calls.push(`lock ${to}`);
    });
  return { doc, screen: { orientation: { lock } }, calls };
}

describe("locking the phone page to landscape", () => {
  it("goes full screen, then locks to landscape, so the camera films sideways even with rotation locked", async () => {
    const { doc, screen, calls } = page();
    expect(await lockLandscape(doc, screen)).toBe("locked");
    expect(calls).toEqual(["fullscreen", "lock landscape"]);
  });

  it("doesn't ask for full screen again", async () => {
    const { doc, screen, calls } = page({ fullscreen: true });
    expect(await lockLandscape(doc, screen)).toBe("locked");
    expect(calls).toEqual(["lock landscape"]);
  });

  it("says when the browser can't lock (an iPhone) or won't", async () => {
    const { doc } = page();
    expect(await lockLandscape(doc, {})).toBe("unsupported");
    const refusing = page({ lock: () => Promise.reject(new Error("NotSupportedError")) });
    expect(await lockLandscape(refusing.doc, refusing.screen)).toBe("refused");
  });

  it("leaves full screen again when the lock is refused, so nothing is left half done", async () => {
    const refusing = page({ lock: () => Promise.reject(new Error("NotSupportedError")) });
    expect(await lockLandscape(refusing.doc, refusing.screen)).toBe("refused");
    expect(refusing.calls).toEqual(["fullscreen", "exit fullscreen"]);
  });
});

describe("what the phone says while its picture is upright", () => {
  it("offers the button wherever the page can lock, and the rotation-lock advice once a lock was tried", () => {
    expect(turnAdvice(null)).toEqual({ button: true, rotationHint: false });
    // Locked, yet still upright (the camera prompt left full screen): try again, or unlock rotation.
    expect(turnAdvice("locked")).toEqual({ button: true, rotationHint: true });
    expect(turnAdvice("refused")).toEqual({ button: true, rotationHint: true });
    // An iPhone can't lock: only the phone's own rotation setting helps.
    expect(turnAdvice("unsupported")).toEqual({ button: false, rotationHint: true });
  });
});
