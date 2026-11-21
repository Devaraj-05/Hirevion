import { describe, expect, it } from "vitest";
import { shownToCandidate } from "./shown";
import type { CheckResult } from "./types";

const pass = (check: string): CheckResult => ({ check, status: "pass" });

describe("shownToCandidate", () => {
  it("shows the camera, microphone, network and display, in that order", () => {
    const all = ["displays", "cpu", "network", "memory", "microphone", "webview2", "camera"].map(
      pass,
    );
    expect(shownToCandidate(all).map((result) => result.check)).toEqual([
      "camera",
      "microphone",
      "network",
      "displays",
    ]);
  });

  it("shows any other check only when it failed, so the candidate can fix it", () => {
    const all: CheckResult[] = [
      pass("camera"),
      { check: "disk", status: "fail", detail: "Free up 2 GB" },
      { check: "cpu", status: "warn", detail: "Slow processor" },
      { check: "screen_capture", status: "fail", detail: "Allow screen recording" },
    ];
    expect(shownToCandidate(all).map((result) => result.check)).toEqual([
      "camera",
      "disk",
      "screen_capture",
    ]);
  });

  it("never shows a skipped check or the phone, which has its own step", () => {
    const all: CheckResult[] = [
      { check: "network", status: "skipped" },
      { check: "third_eye", status: "fail" },
    ];
    expect(shownToCandidate(all)).toEqual([]);
  });
});
