import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./button";
import { DataTable, type DataTableColumn, type DataTableLabels } from "./data-table";
import { localViewStore, type SortingState } from "./view-store";

interface Job {
  id: string;
  title: string;
  location: string;
}

const ROWS: Job[] = [
  { id: "j1", title: "Backend engineer", location: "Bengaluru" },
  { id: "j2", title: "Data analyst", location: "Pune" },
];

const COLUMNS: DataTableColumn<Job>[] = [
  { id: "title", header: "Title", cell: (row) => row.title, sortable: true },
  { id: "location", header: "Location", cell: (row) => row.location },
];

const LABELS: DataTableLabels<Job> = {
  selectAll: "Select all rows",
  selectRow: (row) => `Select ${row.title}`,
  selected: (count) => `${count} selected`,
  clearSelection: "Clear selection",
  columns: "Columns",
  views: "Saved views",
  viewName: "View name",
  saveView: "Save view",
  applyView: (name) => `Apply ${name}`,
  deleteView: (name) => `Delete ${name}`,
  noViews: "No saved views yet",
};

interface HarnessProps {
  rows?: Job[];
  onSort?: (sorting: SortingState) => void;
  onFilters?: (filters: Record<string, string>) => void;
  bulkActions?: (rows: Job[]) => ReactNode;
  emptyState?: ReactNode;
}

function Harness({ rows = ROWS, onSort, onFilters, bulkActions, emptyState }: HarnessProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  return (
    <DataTable
      tableId="jobs"
      caption="Jobs"
      columns={COLUMNS}
      rows={rows}
      getRowId={(row) => row.id}
      labels={LABELS}
      sorting={sorting}
      onSortingChange={(next) => {
        onSort?.(next);
        setSorting(next);
      }}
      filters={{ status: "open" }}
      {...(onFilters ? { onFiltersChange: onFilters } : {})}
      {...(bulkActions ? { bulkActions } : {})}
      {...(emptyState ? { emptyState } : {})}
      viewStore={localViewStore()}
    />
  );
}

describe("DataTable", () => {
  it("asks for the next sort when a sortable header is clicked", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    render(<Harness onSort={onSort} />);
    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(onSort).toHaveBeenLastCalledWith([{ id: "title", desc: false }]);
    expect(screen.getByRole("columnheader", { name: "Title" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    await user.click(screen.getByRole("button", { name: "Title" }));
    expect(onSort).toHaveBeenLastCalledWith([{ id: "title", desc: true }]);
    expect(
      within(screen.getByRole("columnheader", { name: "Location" })).queryByRole("button"),
    ).toBeNull();
  });

  it("shows the selected count and the bulk actions for the selection", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        bulkActions={(rows) => <Button>{`Archive ${rows.map((row) => row.id).join(",")}`}</Button>}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("");
    await user.click(screen.getByRole("checkbox", { name: "Select Backend engineer" }));
    expect(screen.getByRole("status")).toHaveTextContent("1 selected");
    expect(screen.getByRole("button", { name: "Archive j1" })).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Select all rows" }));
    expect(screen.getByRole("status")).toHaveTextContent("2 selected");
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("hides a column from the columns menu", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Columns" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Location" }));
    expect(screen.queryByRole("columnheader", { name: "Location" })).toBeNull();
    expect(screen.queryByText("Pune")).toBeNull();
  });

  it("saves the current view and restores it later", async () => {
    const user = userEvent.setup();
    const onSort = vi.fn();
    const onFilters = vi.fn();
    render(<Harness onSort={onSort} onFilters={onFilters} />);
    await user.click(screen.getByRole("button", { name: "Title" }));
    await user.click(screen.getByRole("button", { name: "Columns" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Location" }));
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Saved views" }));
    await user.type(screen.getByRole("textbox", { name: "View name" }), "Open roles");
    await user.click(screen.getByRole("button", { name: "Save view" }));
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Title" }));
    await user.click(screen.getByRole("button", { name: "Columns" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Location" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("columnheader", { name: "Location" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Saved views" }));
    await user.click(screen.getByRole("button", { name: "Apply Open roles" }));
    expect(onSort).toHaveBeenLastCalledWith([{ id: "title", desc: false }]);
    expect(onFilters).toHaveBeenLastCalledWith({ status: "open" });
    expect(screen.queryByRole("columnheader", { name: "Location" })).toBeNull();
  });

  it("shows the empty state when there are no rows", () => {
    render(<Harness rows={[]} emptyState={<p>No jobs yet</p>} />);
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
  });
});
