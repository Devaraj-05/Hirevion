import { describe, expect, it } from "vitest";
import config from "../src-tauri/tauri.conf.json";

// A 1366×768 or 1920×1080 laptop at 125–150% scaling gives the app about 1280×720 CSS pixels,
// less the taskbar (product owner's PC, 2026-11-15: the window ran off the bottom of the screen).
const SMALL_SCREEN = { width: 1280, height: 720 - 48 };

describe("the main window", () => {
  const main = config.app.windows.find((window) => window.label === "main");

  it("opens maximised, so it fits whatever the screen is", () => {
    expect(main?.maximized).toBe(true);
  });

  it("can shrink to fit a small laptop screen", () => {
    expect(main?.minWidth).toBeLessThanOrEqual(SMALL_SCREEN.width);
    expect(main?.minHeight).toBeLessThanOrEqual(SMALL_SCREEN.height);
  });
});
