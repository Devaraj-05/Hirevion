"use client";

import {
  type ColumnDef,
  type ColumnVisibilityState,
  columnVisibilityFeature,
  functionalUpdate,
  type RowData,
  type RowSelectionState,
  rowSelectionFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Bookmark, ChevronsUpDown, Columns3, Trash } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useMemo, useState } from "react";
import { cn } from "../lib/cn";
import { Button, IconButton } from "./button";
import { Checkbox } from "./choice";
import { Input, Label } from "./input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./menus";
import type { SavedView, SortingState, ViewStore } from "./view-store";

const features = tableFeatures({ rowSortingFeature, rowSelectionFeature, columnVisibilityFeature });

const SELECT_COLUMN = "select";

export interface DataTableColumn<TData> {
  id: string;
  header: string;
  cell: (row: TData) => ReactNode;
  /** Sorted by the server: the table only reports the requested order. */
  sortable?: boolean;
  /** Whether the user may hide it from the columns menu. Defaults to true. */
  hideable?: boolean;
}

/** Every visible string, so the app supplies translations. */
export interface DataTableLabels<TData> {
  selectAll: string;
  selectRow: (row: TData) => string;
  selected: (count: number) => string;
  clearSelection: string;
  columns: string;
  views: string;
  viewName: string;
  saveView: string;
  applyView: (name: string) => string;
  deleteView: (name: string) => string;
  noViews: string;
}

export interface DataTableProps<TData> {
  /** Identifies the table's saved views. */
  tableId: string;
  /** The table's accessible name. */
  caption: string;
  columns: readonly DataTableColumn<TData>[];
  /** Keep this array stable between renders (memoise it, or use a module-level empty array). */
  rows: readonly TData[];
  getRowId: (row: TData) => string;
  labels: DataTableLabels<TData>;
  /** Controlled: the app owns sorting (in the URL) and fetches rows in that order. */
  sorting: SortingState;
  onSortingChange: (sorting: SortingState) => void;
  /** The current filters, kept in saved views and handed back when one is applied. */
  filters?: Readonly<Record<string, string>>;
  onFiltersChange?: (filters: Record<string, string>) => void;
  /** Actions for the selected rows, shown beside the selected count. */
  bulkActions?: (rows: TData[]) => ReactNode;
  emptyState?: ReactNode;
  viewStore?: ViewStore;
  /** Below the table, e.g. pagination. */
  footer?: ReactNode;
}

function ariaSort(direction: false | "asc" | "desc"): "ascending" | "descending" | "none" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}

/** A server-driven table: sorting, selection with bulk actions, column choice and saved views. */
export function DataTable<TData extends RowData>({
  tableId,
  caption,
  columns,
  rows,
  getRowId,
  labels,
  sorting,
  onSortingChange,
  filters,
  onFiltersChange,
  bulkActions,
  emptyState,
  viewStore,
  footer,
}: DataTableProps<TData>) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [columnVisibility, setColumnVisibility] = useState<ColumnVisibilityState>({});

  const definitions = useMemo<ColumnDef<typeof features, TData>[]>(
    () => [
      {
        id: SELECT_COLUMN,
        enableSorting: false,
        enableHiding: false,
        header: ({ table }) => (
          <Checkbox
            aria-label={labels.selectAll}
            checked={
              table.getIsAllRowsSelected()
                ? true
                : table.getIsSomeRowsSelected()
                  ? "indeterminate"
                  : false
            }
            onCheckedChange={(value) => table.toggleAllRowsSelected(value === true)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label={labels.selectRow(row.original)}
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(value === true)}
          />
        ),
      },
      ...columns.map(
        (column): ColumnDef<typeof features, TData> => ({
          id: column.id,
          // Sorting happens on the server; the accessor only marks the column as sortable.
          accessorFn: () => null,
          header: column.header,
          cell: ({ row }) => column.cell(row.original),
          enableSorting: column.sortable ?? false,
          enableHiding: column.hideable ?? true,
        }),
      ),
    ],
    [columns, labels],
  );

  const table = useTable({
    features,
    columns: definitions,
    data: rows,
    getRowId: (row) => getRowId(row),
    manualSorting: true,
    enableMultiSort: false,
    sortDescFirst: false,
    state: { sorting, rowSelection, columnVisibility },
    onSortingChange: (updater) => onSortingChange(functionalUpdate(updater, sorting)),
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
  });

  const selected = table.getSelectedRowModel().rows.map((row) => row.original);
  const headerText = new Map(columns.map((column) => [column.id, column.header]));
  const hideable = table.getAllLeafColumns().filter((column) => column.getCanHide());

  function applyView(view: SavedView) {
    onSortingChange(view.sorting);
    onFiltersChange?.(view.filters);
    setColumnVisibility(view.columnVisibility);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-h-9 items-center gap-2">
          <span role="status" className="text-sm">
            {selected.length > 0 ? labels.selected(selected.length) : ""}
          </span>
          {selected.length > 0 ? (
            <>
              {bulkActions?.(selected)}
              <Button variant="ghost" size="sm" onClick={() => setRowSelection({})}>
                {labels.clearSelection}
              </Button>
            </>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {hideable.length > 0 ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="secondary" size="sm">
                  <Columns3 aria-hidden />
                  {labels.columns}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {hideable.map((column) => (
                  <DropdownMenuCheckboxItem
                    key={column.id}
                    checked={column.getIsVisible()}
                    onCheckedChange={(value) => column.toggleVisibility(value === true)}
                    onSelect={(event) => event.preventDefault()}
                  >
                    {headerText.get(column.id) ?? column.id}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          {viewStore ? (
            <SavedViews
              tableId={tableId}
              store={viewStore}
              labels={labels}
              current={() => ({ sorting, filters: { ...filters }, columnVisibility })}
              onApply={applyView}
            />
          ) : null}
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-surface-muted text-left">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const column = header.column;
                  const sortable = column.getCanSort();
                  const direction = column.getIsSorted();
                  const SortIcon =
                    direction === "asc"
                      ? ArrowUp
                      : direction === "desc"
                        ? ArrowDown
                        : ChevronsUpDown;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sortable ? ariaSort(direction) : undefined}
                      className={cn(
                        "border-border border-b px-3 py-2 font-medium text-muted-foreground",
                        column.id === SELECT_COLUMN && "w-10",
                      )}
                    >
                      {header.isPlaceholder ? null : sortable ? (
                        <button
                          type="button"
                          onClick={column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 rounded-sm hover:text-foreground"
                        >
                          <table.FlexRender header={header} />
                          <SortIcon className="size-3.5" aria-hidden />
                        </button>
                      ) : (
                        <table.FlexRender header={header} />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={table.getVisibleLeafColumns().length} className="p-4">
                  {emptyState}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  data-state={row.getIsSelected() ? "selected" : undefined}
                  className="border-border border-b last:border-b-0 data-[state=selected]:bg-accent-subtle"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3 py-2">
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {footer}
    </div>
  );
}

interface SavedViewsProps<TData> {
  tableId: string;
  store: ViewStore;
  labels: DataTableLabels<TData>;
  current: () => Omit<SavedView, "name">;
  onApply: (view: SavedView) => void;
}

function SavedViews<TData>({ tableId, store, labels, current, onApply }: SavedViewsProps<TData>) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [name, setName] = useState("");
  const inputId = useId();

  function save(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    store.save(tableId, { name: trimmed, ...current() });
    setViews(store.list(tableId));
    setName("");
  }

  function remove(viewName: string) {
    store.remove(tableId, viewName);
    setViews(store.list(tableId));
  }

  return (
    // Read on open, so the server render (no storage) and the first client render agree.
    <Popover onOpenChange={(open) => open && setViews(store.list(tableId))}>
      <PopoverTrigger asChild>
        <Button variant="secondary" size="sm">
          <Bookmark aria-hidden />
          {labels.views}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex flex-col gap-3">
        {views.length === 0 ? (
          <p className="text-muted-foreground text-sm">{labels.noViews}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {views.map((view) => (
              <li key={view.name} className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="flex-1 justify-start"
                  aria-label={labels.applyView(view.name)}
                  onClick={() => onApply(view)}
                >
                  {view.name}
                </Button>
                <IconButton
                  label={labels.deleteView(view.name)}
                  icon={<Trash aria-hidden />}
                  onClick={() => remove(view.name)}
                />
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={save} className="flex items-end gap-2 border-border border-t pt-3">
          <div className="flex flex-1 flex-col gap-1">
            <Label htmlFor={inputId}>{labels.viewName}</Label>
            <Input
              id={inputId}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>
          <Button type="submit" size="sm">
            {labels.saveView}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
