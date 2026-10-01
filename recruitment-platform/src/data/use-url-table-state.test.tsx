import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { resetNavigation, router } from "@/test/navigation";
import { useUrlTableState } from "./use-url-table-state";

describe("useUrlTableState", () => {
  it("reads the table state from the URL and writes changes back to it", () => {
    resetNavigation("/jobs", "status=open");
    const { result } = renderHook(() => useUrlTableState(["status"]));
    expect(result.current.filters).toEqual({ status: "open" });
    act(() => result.current.setSorting([{ id: "title", desc: true }]));
    expect(router.replace).toHaveBeenCalledWith("/jobs?status=open&sort=-title", { scroll: false });
    act(() => result.current.setFilters({ status: "" }));
    expect(router.replace).toHaveBeenLastCalledWith("/jobs", { scroll: false });
  });
});
