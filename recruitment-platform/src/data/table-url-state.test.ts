import { describe, expect, it } from "vitest";
import { parseTableState, writeTableState } from "./table-url-state";

const KEYS = ["status", "location"] as const;

describe("table state in the URL", () => {
  it("reads the sort and the known filters", () => {
    const params = new URLSearchParams("sort=-title&status=open&unrelated=1");
    expect(parseTableState(params, KEYS)).toEqual({
      sorting: [{ id: "title", desc: true }],
      filters: { status: "open" },
    });
  });

  it("writes them back, keeping unrelated parameters and dropping empty filters", () => {
    const params = writeTableState(
      new URLSearchParams("tab=open&location=pune"),
      { sorting: [{ id: "title", desc: false }], filters: { status: "open", location: "" } },
      KEYS,
    );
    expect(params.toString()).toBe("tab=open&sort=title&status=open");
    expect(parseTableState(params, KEYS)).toEqual({
      sorting: [{ id: "title", desc: false }],
      filters: { status: "open" },
    });
  });

  it("removes the sort when it is cleared", () => {
    const params = writeTableState(
      new URLSearchParams("sort=title"),
      { sorting: [], filters: {} },
      KEYS,
    );
    expect(params.has("sort")).toBe(false);
  });

  it("ignores a malformed sort", () => {
    expect(parseTableState(new URLSearchParams("sort=-"), KEYS).sorting).toEqual([]);
  });
});
