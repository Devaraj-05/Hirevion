import { describe, expect, it } from "vitest";
import { liveView, onlyThirdEyeFailed, phoneState } from "./pairing";

describe("the phone step", () => {
  it("names what the candidate sees for each pairing status", () => {
    expect(phoneState("issued")).toBe("waiting");
    expect(phoneState("redeemed")).toBe("starting");
    expect(phoneState("connected")).toBe("connected");
    // A lock unpublishes the camera: it comes back by itself, no new code.
    expect(phoneState("disconnected")).toBe("reconnecting");
    expect(phoneState("expired")).toBe("new-code");
    expect(phoneState("revoked")).toBe("new-code");
    expect(phoneState("something-new")).toBe("waiting");
  });

  it("lets a check that failed only on the third eye wait for the phone", () => {
    expect(onlyThirdEyeFailed(["third_eye"])).toBe(true);
    expect(onlyThirdEyeFailed(["camera", "third_eye"])).toBe(false);
    expect(onlyThirdEyeFailed([])).toBe(false);
  });
});

describe("the third eye during the interview", () => {
  it("shows the phone's camera as the heartbeat reports it", () => {
    expect(liveView("connected")).toEqual({ tone: "success", alert: false });
    expect(liveView("connecting")).toEqual({ tone: "warning", alert: false });
    // A lost camera is worth telling the candidate, so they can unlock the phone.
    expect(liveView("disconnected")).toEqual({ tone: "warning", alert: true });
    expect(liveView("not_paired")).toEqual({ tone: "neutral", alert: false });
  });
});
