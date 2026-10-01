import type { SortingState } from "@hirevion/ui";

/** A table's sort and filters as URL search parameters, so views can be linked and reloaded. */

export interface TableState {
  sorting: SortingState;
  filters: Record<string, string>;
}

const SORT = "sort";

/** `sort=title` is ascending and `sort=-title` descending; filters are their own parameters. */
export function parseTableState(
  params: URLSearchParams,
  filterKeys: readonly string[],
): TableState {
  const raw = params.get(SORT) ?? "";
  const desc = raw.startsWith("-");
  const id = desc ? raw.slice(1) : raw;
  const filters: Record<string, string> = {};
  for (const key of filterKeys) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return { sorting: id ? [{ id, desc }] : [], filters };
}

/** A copy of `base` carrying `state`; other parameters keep their place. */
export function writeTableState(
  base: URLSearchParams,
  state: TableState,
  filterKeys: readonly string[],
): URLSearchParams {
  const params = new URLSearchParams(base);
  const [sort] = state.sorting;
  if (sort) params.set(SORT, `${sort.desc ? "-" : ""}${sort.id}`);
  else params.delete(SORT);
  for (const key of filterKeys) {
    const value = state.filters[key];
    if (value) params.set(key, value);
    else params.delete(key);
  }
  return params;
}
