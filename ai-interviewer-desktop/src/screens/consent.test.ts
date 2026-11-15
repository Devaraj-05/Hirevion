import { describe, expect, it } from "vitest";
import { agreeToTerms } from "./consent";

describe("agreeing to the Terms and Conditions", () => {
  it("accepts every item of the notice it was shown, in one click", () => {
    const body = agreeToTerms({
      version: "2026-11-15",
      items: [
        { purpose: "camera", text: "Your camera", required: true },
        { purpose: "third_eye", text: "Your phone", required: false },
        { purpose: "transcript", text: "What you say", required: true },
      ],
    });
    expect(body).toEqual({
      notice_version: "2026-11-15",
      items: [
        { purpose: "camera", accepted: true },
        { purpose: "third_eye", accepted: true },
        { purpose: "transcript", accepted: true },
      ],
    });
  });
});
