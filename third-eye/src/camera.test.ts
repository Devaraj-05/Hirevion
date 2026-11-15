import { describe, expect, it } from "vitest";
import { captureOptions, needsTurning, nextFacing } from "./camera";

describe("switching the phone's camera", () => {
  it("flips between the rear and the front camera", () => {
    expect(nextFacing("environment")).toBe("user");
    expect(nextFacing("user")).toBe("environment");
  });

  it("asks to turn the phone sideways while its picture is taller than wide", () => {
    expect(needsTurning(720, 1280)).toBe(true);
    expect(needsTurning(1280, 720)).toBe(false);
    expect(needsTurning(0, 0)).toBe(false); // no picture yet
  });

  it("keeps 720p at 15 fps whichever camera it uses", () => {
    expect(captureOptions("user")).toEqual({
      facingMode: "user",
      resolution: { width: 1280, height: 720, frameRate: 15 },
    });
    expect(captureOptions("environment").facingMode).toBe("environment");
  });
});
