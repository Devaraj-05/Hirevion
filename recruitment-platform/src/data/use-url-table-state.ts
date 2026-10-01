"use client";

import type { SortingState } from "@hirevion/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { parseTableState, type TableState, writeTableState } from "./table-url-state";

/** A table's sort and filters, owned by the URL; changes replace the history entry. */
export function useUrlTableState(filterKeys: readonly string[]) {
  const search = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const state = parseTableState(new URLSearchParams(search.toString()), filterKeys);

  function go(next: TableState) {
    const query = writeTableState(
      new URLSearchParams(search.toString()),
      next,
      filterKeys,
    ).toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return {
    ...state,
    setSorting: (sorting: SortingState) => go({ ...state, sorting }),
    setFilters: (filters: Record<string, string>) => go({ ...state, filters }),
  };
}
