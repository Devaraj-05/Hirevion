import { describe, expect, it } from "vitest";
import { lockLandscape } from "./orientation";

function page(options: { fullscreen?: boolean; lock?: (to: string) => Promise<void> } = {}) {
  const calls: string[] = [];
  const doc = {
    fullscreenElement: options.fullscreen ? ({} as Element) : null,
    documentElement: {
      requestFullscreen: async () => {
        calls.push("fullscreen");
      },
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
});
