import { describe, expect, it } from "vitest";
import { typedAnswers, workspaceOf } from "./workspace";

describe("the coding column (C8-12)", () => {
  it("opens only for a coding or a design question", () => {
    expect(workspaceOf({ workspace: "code" })).toBe("code");
    expect(workspaceOf({ workspace: "whiteboard" })).toBe("notes");
    expect(workspaceOf({ workspace: "none" })).toBeNull();
    expect(workspaceOf(null)).toBeNull();
    expect(workspaceOf(undefined)).toBeNull();
  });

  it("offers typed answers only where speech can't be used, never on the coding question", () => {
    expect(typedAnswers("voice", "connected", null)).toBe(false);
    expect(typedAnswers("text", "connected", null)).toBe(true);
    expect(typedAnswers("voice", "off", "notes")).toBe(true);
    expect(typedAnswers("text", "off", "code")).toBe(false);
  });
});
