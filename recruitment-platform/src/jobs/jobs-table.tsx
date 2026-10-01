"use client";

import { DataTable, type DataTableColumn, EmptyState, localViewStore } from "@hirevion/ui";
import { Briefcase } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";

/** A job as the list shows it. SP-04 supplies these from GET /api/v1/jobs. */
export interface JobRow {
  id: string;
  title: string;
  department: string;
  location: string;
  status: string;
  candidates: number;
  updated: string;
}

const NO_JOBS: JobRow[] = [];
const FILTERS = ["status"] as const;
const jobName = (job: JobRow) => job.title;

/** The jobs list: sort and the status tab live in the URL; rows arrive with SP-04. */
export function JobsTable() {
  const t = useTranslations("jobs.table");
  const labels = useTableLabels(jobName);
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const columns = useMemo<DataTableColumn<JobRow>[]>(
    () => [
      {
        id: "title",
        header: t("title"),
        cell: (job) => job.title,
        sortable: true,
        hideable: false,
      },
      { id: "department", header: t("department"), cell: (job) => job.department },
      { id: "location", header: t("location"), cell: (job) => job.location },
      { id: "status", header: t("status"), cell: (job) => job.status },
      { id: "candidates", header: t("candidates"), cell: (job) => job.candidates },
      { id: "updated", header: t("updated"), cell: (job) => job.updated, sortable: true },
    ],
    [t],
  );

  return (
    <DataTable
      tableId="jobs"
      caption={t("caption")}
      columns={columns}
      rows={NO_JOBS}
      getRowId={(job) => job.id}
      labels={labels}
      sorting={sorting}
      onSortingChange={setSorting}
      filters={filters}
      onFiltersChange={setFilters}
      viewStore={viewStore}
      emptyState={
        <EmptyState
          icon={<Briefcase />}
          title={t("emptyTitle")}
          description={t("emptyHint", { owner: "SP-04" })}
        />
      }
    />
  );
}
