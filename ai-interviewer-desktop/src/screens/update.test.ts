import { describe, expect, it } from "vitest";
import { applyProgress, failureReason, progressPercent } from "./update";

describe("update progress", () => {
  it("is a whole percent, bounded, or unknown without a size", () => {
    expect(progressPercent(0, 200)).toBe(0);
    expect(progressPercent(50, 200)).toBe(25);
    expect(progressPercent(199, 200)).toBe(99);
    expect(progressPercent(400, 200)).toBe(100);
    expect(progressPercent(10, null)).toBeNull();
    expect(progressPercent(10, 0)).toBeNull();
  });

  it("follows the download, then the install", () => {
    expect(applyProgress({ event: "downloading", downloaded: 5, total: 10 })).toEqual({
      step: "downloading",
      downloaded: 5,
      total: 10,
    });
    expect(applyProgress({ event: "installing" })).toEqual({ step: "installing" });
  });
});

describe("why an update failed", () => {
  it("separates a bad signature, no network and a missing release", () => {
    expect(failureReason({ code: "update-signature-invalid" })).toBe("signature");
    expect(failureReason({ code: "network" })).toBe("network");
    expect(failureReason({ code: "update-unavailable" })).toBe("unavailable");
    expect(failureReason({ code: "update-failed", detail: "disk full" })).toBe("failed");
    expect(failureReason(new Error("x"))).toBe("failed");
  });
});
