import { describe, expect, it } from "vitest";
import { statusActions } from "./status";

describe("statusActions", () => {
  it("offers only the moves the API allows", () => {
    expect(statusActions("draft")).toEqual([{ action: "open", to: "open" }]);
    expect(statusActions("open").map((a) => a.action)).toEqual(["pause", "close"]);
    expect(statusActions("paused").map((a) => a.action)).toEqual(["resume", "close"]);
    expect(statusActions("closed").map((a) => a.action)).toEqual(["archive"]);
    expect(statusActions("archived")).toEqual([]);
  });
});
