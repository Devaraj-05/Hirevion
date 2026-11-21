import { describe, expect, it } from "vitest";
import { type Done, readyToStart, steps } from "./steps";

const none: Done = { devices: false, checks: false, terms: false, phone: false };

describe("the steps on the one page before the interview (owner, 2026-11-16)", () => {
  it("runs camera and microphone, the system check, the terms, then the phone, in that order", () => {
    expect(steps(none, "required")).toEqual([
      { id: "devices", state: "active" },
      { id: "checks", state: "locked" },
      { id: "terms", state: "locked" },
      { id: "phone", state: "locked" },
    ]);
    expect(steps({ ...none, devices: true, checks: true }, "required").map((s) => s.state)).toEqual(
      ["done", "done", "active", "locked"],
    );
  });

  it("has no phone step when the interview doesn't use one", () => {
    expect(steps(none, "off").map((s) => s.id)).toEqual(["devices", "checks", "terms"]);
  });

  it("can start only when every step is done", () => {
    const all: Done = { devices: true, checks: true, terms: true, phone: true };
    expect(readyToStart({ ...all, phone: false }, "required")).toBe(false);
    expect(readyToStart({ ...all, phone: false }, "off")).toBe(true);
    expect(readyToStart(all, "optional")).toBe(true);
  });

  it("keeps a later step locked while an earlier one is undone again", () => {
    // The camera was lost after the check passed: back to the first step.
    expect(steps({ ...none, checks: true }, "off").map((s) => s.state)).toEqual([
      "active",
      "locked",
      "locked",
    ]);
  });
});
