import { describe, expect, it } from "vitest";
import { captureOptions, nextFacing } from "./camera";

describe("switching the phone's camera", () => {
  it("flips between the rear and the front camera", () => {
    expect(nextFacing("environment")).toBe("user");
    expect(nextFacing("user")).toBe("environment");
  });

  it("keeps 720p at 15 fps whichever camera it uses", () => {
    expect(captureOptions("user")).toEqual({
      facingMode: "user",
      resolution: { width: 1280, height: 720, frameRate: 15 },
    });
    expect(captureOptions("environment").facingMode).toBe("environment");
  });
});
