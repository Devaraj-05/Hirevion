import { describe, expect, it } from "vitest";
import {
  applyProgress,
  failureReason,
  isBusy,
  outcomeState,
  progressPercent,
  type UpdateState,
} from "./update";

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
    const checking: UpdateState = { step: "checking" };
    const downloading = applyProgress(checking, { event: "downloading", downloaded: 5, total: 10 });
    expect(downloading).toEqual({ step: "downloading", downloaded: 5, total: 10 });
    expect(applyProgress(downloading, { event: "installing" })).toEqual({ step: "installing" });
  });

  it("ignores a progress message that arrives after the command has settled", () => {
    // Channel messages can overtake or trail the invoke's own reply.
    const settled: UpdateState[] = [
      { step: "failed", reason: "signature" },
      { step: "up-to-date" },
      { step: "restart" },
      { step: "idle" },
    ];
    for (const state of settled) {
      expect(applyProgress(state, { event: "installing" })).toBe(state);
      expect(applyProgress(state, { event: "downloading", downloaded: 9, total: 10 })).toBe(state);
    }
  });
});

describe("the end of an update", () => {
  it("an installed update ends in a restart prompt, never a busy state", () => {
    const state = outcomeState("installed");
    expect(state).toEqual({ step: "restart" });
    expect(isBusy(state)).toBe(false);
  });

  it("nothing newer is a settled state too", () => {
    expect(outcomeState("up-to-date")).toEqual({ step: "up-to-date" });
  });

  it("only checking, downloading and installing keep the button disabled", () => {
    expect(isBusy({ step: "checking" })).toBe(true);
    expect(isBusy({ step: "downloading", downloaded: 0, total: null })).toBe(true);
    expect(isBusy({ step: "installing" })).toBe(true);
    expect(isBusy({ step: "idle" })).toBe(false);
    expect(isBusy({ step: "failed", reason: "network" })).toBe(false);
    expect(isBusy({ step: "up-to-date" })).toBe(false);
    expect(isBusy({ step: "restart" })).toBe(false);
  });
});

describe("why an update failed", () => {
  it("separates a bad signature, no network, a server problem and a missing release", () => {
    expect(failureReason({ code: "update-signature-invalid" })).toBe("signature");
    expect(failureReason({ code: "network" })).toBe("network");
    expect(failureReason({ code: "update-server-error", detail: "HTTP 503" })).toBe("server");
    expect(failureReason({ code: "update-unavailable" })).toBe("unavailable");
    expect(failureReason({ code: "update-failed", detail: "disk full" })).toBe("failed");
    expect(failureReason(new Error("x"))).toBe("failed");
  });
});
