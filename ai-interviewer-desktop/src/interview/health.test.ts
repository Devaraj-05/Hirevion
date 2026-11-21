import { describe, expect, it } from "vitest";
import { indicators } from "./health";

describe("PRD §32's status strip during the interview", () => {
  it("says starting until the services first all start", () => {
    expect(indicators(null, null)).toEqual({
      camera: "starting",
      microphone: "starting",
      screen: "starting",
      phone: null,
    });
  });

  it("marks the parts a problem touches, and only those", () => {
    expect(indicators(new Set(["vision"]), "connected")).toEqual({
      camera: "problem",
      microphone: "ok",
      screen: "ok",
      phone: "ok",
    });
    // The recorder holds the camera, the microphone and the screen.
    expect(indicators(new Set(["recording"]), null)).toMatchObject({
      camera: "problem",
      microphone: "problem",
      screen: "problem",
    });
  });

  it("follows the phone's camera, and leaves it out when the interview has none", () => {
    expect(indicators(new Set(), "connecting").phone).toBe("starting");
    expect(indicators(new Set(), "disconnected").phone).toBe("problem");
    expect(indicators(new Set(), "not_required").phone).toBeNull();
  });
});
