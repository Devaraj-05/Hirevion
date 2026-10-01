/** Saved table views: a named sort, filter set and column choice the user can return to. */

export type SortingState = Array<{ id: string; desc: boolean }>;

export interface SavedView {
  name: string;
  sorting: SortingState;
  filters: Record<string, string>;
  columnVisibility: Record<string, boolean>;
}

export interface ViewStore {
  list(tableId: string): SavedView[];
  save(tableId: string, view: SavedView): void;
  remove(tableId: string, name: string): void;
}

const PREFIX = "hv_views:";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSavedView(value: unknown): value is SavedView {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    Array.isArray(value.sorting) &&
    isRecord(value.filters) &&
    isRecord(value.columnVisibility)
  );
}

/**
 * Views kept in this browser's localStorage. Blocked or full storage loses the view rather
 * than breaking the table. SP-22 adds a server-backed store shared across devices.
 */
export function localViewStore(storage: () => Storage = () => window.localStorage): ViewStore {
  function read(tableId: string): SavedView[] {
    try {
      const raw = storage().getItem(`${PREFIX}${tableId}`);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter(isSavedView) : [];
    } catch {
      return [];
    }
  }

  function write(tableId: string, views: SavedView[]): void {
    try {
      storage().setItem(`${PREFIX}${tableId}`, JSON.stringify(views));
    } catch {
      // Storage is blocked or full; the view isn't kept.
    }
  }

  return {
    list: read,
    save(tableId, view) {
      write(tableId, [...read(tableId).filter((saved) => saved.name !== view.name), view]);
    },
    remove(tableId, name) {
      write(
        tableId,
        read(tableId).filter((saved) => saved.name !== name),
      );
    },
  };
}
