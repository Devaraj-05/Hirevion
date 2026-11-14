import { describe, expect, it } from "vitest";
import { onlyThirdEyeFailed, phoneState } from "./pairing";

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
