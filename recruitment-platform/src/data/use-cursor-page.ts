"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

/** One page of a cursor-paginated API list (ADR-0010). */
export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

const NO_ROWS: never[] = [];

/**
 * Pages through a cursor-paginated list. The API only goes forward, so the cursors already
 * visited are kept as a stack for going back. A new query (other filters or sort) starts over.
 */
export function useCursorPage<T>(
  queryKey: readonly unknown[],
  fetchPage: (cursor: string | null) => Promise<CursorPage<T>>,
) {
  const key = JSON.stringify(queryKey);
  const [stack, setStack] = useState<{ key: string; cursors: (string | null)[] }>({
    key,
    cursors: [null],
  });
  const cursors = stack.key === key ? stack.cursors : [null];
  const cursor = cursors.at(-1) ?? null;

  const query = useQuery({
    queryKey: [...queryKey, { cursor }],
    queryFn: () => fetchPage(cursor),
    placeholderData: keepPreviousData,
  });
  const page = query.isPlaceholderData ? undefined : query.data;

  return {
    rows: (query.data?.items ?? NO_ROWS) as readonly T[],
    isLoading: query.isPending,
    isFetching: query.isFetching,
    error: query.error,
    refetch: () => void query.refetch(),
    hasNext: Boolean(page?.next_cursor),
    hasPrevious: cursors.length > 1,
    nextPage() {
      const next = page?.next_cursor;
      if (next) setStack({ key, cursors: [...cursors, next] });
    },
    previousPage() {
      if (cursors.length > 1) setStack({ key, cursors: cursors.slice(0, -1) });
    },
  };
}
