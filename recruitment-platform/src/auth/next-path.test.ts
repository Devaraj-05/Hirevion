import { describe, expect, it } from "vitest";
import { safeNext } from "./next-path";

describe("safeNext", () => {
  it("keeps a path on this site", () => {
    expect(safeNext("/jobs?status=open")).toBe("/jobs?status=open");
  });

  it("refuses anything that could leave the site", () => {
    for (const target of [
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "javascript:alert(1)",
      "",
    ]) {
      expect(safeNext(target), target).toBe("/dashboard");
    }
    expect(safeNext(null)).toBe("/dashboard");
  });

  it("doesn't send a signed-in visitor back to sign in", () => {
    expect(safeNext("/login?next=/jobs")).toBe("/dashboard");
  });
});
