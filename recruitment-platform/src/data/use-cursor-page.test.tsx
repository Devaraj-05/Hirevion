import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { type CursorPage, useCursorPage } from "./use-cursor-page";

const PAGES: Record<string, CursorPage<string>> = {
  first: { items: ["a", "b"], next_cursor: "c2" },
  c2: { items: ["c", "d"], next_cursor: "c3" },
  c3: { items: ["e"], next_cursor: null },
};

function fetcher() {
  return vi.fn(async (cursor: string | null) => {
    const page = PAGES[cursor ?? "first"];
    if (!page) throw new Error(`no page ${cursor}`);
    return page;
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCursorPage", () => {
  it("moves forward and back with the right cursors", async () => {
    const fetchPage = fetcher();
    const { result } = renderHook(() => useCursorPage(["jobs"], fetchPage), { wrapper });
    await waitFor(() => expect(result.current.rows).toEqual(["a", "b"]));
    expect(result.current).toMatchObject({ hasPrevious: false, hasNext: true });

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.rows).toEqual(["c", "d"]));
    expect(fetchPage).toHaveBeenLastCalledWith("c2");

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.rows).toEqual(["e"]));
    expect(result.current).toMatchObject({ hasPrevious: true, hasNext: false });

    act(() => result.current.previousPage());
    await waitFor(() => expect(result.current.rows).toEqual(["c", "d"]));
    act(() => result.current.previousPage());
    await waitFor(() => expect(result.current.rows).toEqual(["a", "b"]));
    expect(result.current.hasPrevious).toBe(false);
  });

  it("starts from the first page again when the query changes", async () => {
    const fetchPage = fetcher();
    const { result, rerender } = renderHook(({ query }) => useCursorPage(query, fetchPage), {
      wrapper,
      initialProps: { query: ["jobs", "open"] as const as readonly unknown[] },
    });
    await waitFor(() => expect(result.current.rows).toEqual(["a", "b"]));
    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.rows).toEqual(["c", "d"]));

    rerender({ query: ["jobs", "paused"] });
    await waitFor(() => expect(result.current.rows).toEqual(["a", "b"]));
    expect(result.current.hasPrevious).toBe(false);
    expect(fetchPage).toHaveBeenLastCalledWith(null);
  });
});
