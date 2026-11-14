import { describe, expect, it } from "vitest";
import { fitFrame } from "./frame";

describe("the size of an evidence picture", () => {
  it("keeps the shape, scales down to 1280x720 at most, and never up", () => {
    expect(fitFrame(1920, 1080)).toEqual({ width: 1280, height: 720 });
    expect(fitFrame(640, 480)).toEqual({ width: 640, height: 480 });
    expect(fitFrame(1080, 1920)).toEqual({ width: 405, height: 720 });
    expect(fitFrame(0, 0)).toEqual({ width: 0, height: 0 });
  });
});
