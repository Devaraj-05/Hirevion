import { describe, expect, it } from "vitest";
import { describeMediaError, mediaFailure } from "./errors";

function domError(name: string, message = ""): Error {
  const error = new Error(message);
  error.name = name;
  return error;
}

describe("describeMediaError", () => {
  it("points a blocked device to its Windows privacy page", () => {
    expect(describeMediaError(domError("NotAllowedError"), "camera")).toContain(
      "ms-settings:privacy-webcam",
    );
    expect(describeMediaError(domError("NotAllowedError"), "microphone")).toContain(
      "ms-settings:privacy-microphone",
    );
    expect(describeMediaError(domError("SecurityError"), "camera")).toContain(
      "ms-settings:privacy-webcam",
    );
  });

  it("says when no device is connected", () => {
    expect(describeMediaError(domError("NotFoundError"), "camera")).toMatch(/no camera/i);
    expect(describeMediaError(domError("OverconstrainedError"), "microphone")).toMatch(
      /no microphone/i,
    );
  });

  it("says when another app holds the device", () => {
    expect(describeMediaError(domError("NotReadableError"), "camera")).toMatch(/another app/i);
  });

  it("passes other errors' messages through", () => {
    expect(describeMediaError(domError("TypeError", "bad constraint"), "camera")).toContain(
      "bad constraint",
    );
    expect(describeMediaError("weird", "microphone")).toContain("weird");
  });
});

describe("mediaFailure", () => {
  it("is a failed result with the description as its detail", () => {
    expect(mediaFailure("camera", domError("NotFoundError"))).toEqual({
      check: "camera",
      status: "fail",
      value: "not available",
      detail: describeMediaError(domError("NotFoundError"), "camera"),
    });
  });
});
