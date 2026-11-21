import { describe, expect, it } from "vitest";
import type { AppsToClose } from "../native/commands";
import { appsVerdict } from "./apps";

const app = (name: string) => ({ name, window_title: null, category: null });

describe("appsVerdict", () => {
  it("asks for a blocked app to be closed before anything else", () => {
    const apps: AppsToClose = {
      blocked: [app("ChatGPT.exe")],
      background: [app("AnyDesk.exe")],
      open: [app("chrome.exe")],
    };
    expect(appsVerdict(apps)).toBe("close");
  });

  it("advises closing other open apps", () => {
    expect(appsVerdict({ blocked: [], background: [], open: [app("chrome.exe")] })).toBe("advise");
  });

  it("is clear with nothing open, or when the interview doesn't check apps", () => {
    expect(appsVerdict({ blocked: [], background: [], open: [] })).toBe("clear");
    expect(appsVerdict(null)).toBe("clear");
  });

  it("never holds Start back for a blocked app without a window, which may be a service", () => {
    expect(appsVerdict({ blocked: [], background: [app("AnyDesk.exe")], open: [] })).toBe("advise");
  });

  it("asks the candidate to close apps themselves when the look failed", () => {
    expect(appsVerdict("failed")).toBe("advise");
  });
});
