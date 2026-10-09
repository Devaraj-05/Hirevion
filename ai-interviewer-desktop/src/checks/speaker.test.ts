import { describe, expect, it } from "vitest";
import { speakerResult } from "./speaker";

describe("speakerResult", () => {
  it("passes when the candidate heard the tone", () => {
    expect(speakerResult(true)).toEqual({
      check: "speaker",
      status: "pass",
      value: "test tone heard",
    });
  });

  it("fails with advice when they didn't", () => {
    const result = speakerResult(false);
    expect(result).toMatchObject({
      check: "speaker",
      status: "fail",
      value: "test tone not heard",
    });
    expect(result.detail).toBeTruthy();
  });
});
