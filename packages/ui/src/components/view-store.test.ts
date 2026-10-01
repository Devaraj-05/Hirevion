import { describe, expect, it } from "vitest";
import { localViewStore, type SavedView } from "./view-store";

const OPEN_ROLES: SavedView = {
  name: "Open roles",
  sorting: [{ id: "title", desc: false }],
  filters: { status: "open" },
  columnVisibility: { location: false },
};

describe("localViewStore", () => {
  it("saves, lists and removes views per table", () => {
    const store = localViewStore();
    store.save("jobs", OPEN_ROLES);
    store.save("jobs", { ...OPEN_ROLES, name: "Newest" });
    store.save("candidates", { ...OPEN_ROLES, name: "Shortlist" });
    expect(store.list("jobs").map((view) => view.name)).toEqual(["Open roles", "Newest"]);
    store.remove("jobs", "Open roles");
    expect(store.list("jobs").map((view) => view.name)).toEqual(["Newest"]);
    expect(store.list("candidates")).toHaveLength(1);
  });

  it("replaces a view saved again under the same name", () => {
    const store = localViewStore();
    store.save("jobs", OPEN_ROLES);
    store.save("jobs", { ...OPEN_ROLES, filters: { status: "paused" } });
    expect(store.list("jobs")).toEqual([{ ...OPEN_ROLES, filters: { status: "paused" } }]);
  });

  it("survives storage that throws", () => {
    const store = localViewStore(() => {
      throw new Error("SecurityError");
    });
    expect(() => store.save("jobs", OPEN_ROLES)).not.toThrow();
    expect(store.list("jobs")).toEqual([]);
    expect(() => store.remove("jobs", "Open roles")).not.toThrow();
  });

  it("ignores stored data it doesn't recognise", () => {
    localStorage.setItem("hv_views:jobs", "{not json");
    expect(localViewStore().list("jobs")).toEqual([]);
    localStorage.setItem("hv_views:jobs", JSON.stringify([{ name: 3 }, OPEN_ROLES]));
    expect(localViewStore().list("jobs")).toEqual([OPEN_ROLES]);
  });
});
