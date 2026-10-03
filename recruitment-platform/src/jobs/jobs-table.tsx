"use client";

import {
  Badge,
  Button,
  DataTable,
  type DataTableColumn,
  EmptyState,
  Input,
  localViewStore,
  NativeSelect,
} from "@hirevion/ui";
import { Briefcase, Plus } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";
import { type JobStatus, type JobSummary, listJobs } from "./api";
import { keys, useJobChoices } from "./queries";
import { STATUS_TONES } from "./status";

const FILTERS = ["status", "department", "q"] as const;
const ANY = "";
const PAGE_SIZE = 25;
const jobName = (job: JobSummary) => job.title;

/** The jobs the reader reaches (PRD §11): the status tab, department and search live in the
 * URL; the newest changes come first. */
export function JobsTable({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations("jobs.table");
  const statuses = useTranslations("jobs.statuses");
  const format = useFormatter();
  const labels = useTableLabels(jobName);
  const choices = useJobChoices();
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");

  const query = {
    status: (filters.status || undefined) as JobStatus | undefined,
    department_id: filters.department || undefined,
    q: filters.q || undefined,
  };
  const page = useCursorPage([...keys.list, query], (cursor) =>
    listJobs({ ...query, cursor, limit: PAGE_SIZE }),
  );
  const filtered = Boolean(query.status || query.department_id || query.q);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const columns = useMemo<DataTableColumn<JobSummary>[]>(
    () => [
      {
        id: "title",
        header: t("title"),
        hideable: false,
        cell: (job) => (
          <Link
            href={`/jobs/${job.id}`}
            aria-label={t("open", { title: job.title })}
            className="grid hover:underline focus-visible:underline"
          >
            <span className="font-medium">{job.title}</span>
            <span className="text-muted-foreground text-xs">{job.reference}</span>
          </Link>
        ),
      },
      { id: "department", header: t("department"), cell: (job) => job.department_name ?? "—" },
      { id: "location", header: t("location"), cell: (job) => job.location ?? "—" },
      {
        id: "status",
        header: t("status"),
        cell: (job) => <Badge tone={STATUS_TONES[job.status]}>{statuses(job.status)}</Badge>,
      },
      { id: "recruiter", header: t("recruiter"), cell: (job) => job.recruiter_name ?? "—" },
      {
        id: "updated",
        header: t("updated"),
        cell: (job) => format.dateTime(new Date(job.updated_at), { dateStyle: "medium" }),
      },
    ],
    [t, statuses, format],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <form onSubmit={submitSearch} className="min-w-56 flex-1">
          <Input
            type="search"
            aria-label={t("search")}
            placeholder={t("search")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </form>
        <NativeSelect
          aria-label={t("department")}
          className="w-52"
          value={filters.department ?? ANY}
          onChange={(event) => setFilters({ ...filters, department: event.target.value })}
          options={[
            { value: ANY, label: t("anyDepartment") },
            ...(choices.data?.departments ?? []).map((department) => ({
              value: department.id,
              label: department.name,
            })),
          ]}
        />
        {canCreate ? (
          <Button asChild>
            <Link href="/jobs/new">
              <Plus className="size-4" aria-hidden />
              {t("new")}
            </Link>
          </Button>
        ) : null}
      </div>
      <DataTable
        tableId="jobs"
        caption={t("caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(job) => job.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : (
            <EmptyState
              icon={<Briefcase />}
              title={filtered ? t("noMatchTitle") : t("emptyTitle")}
              description={filtered ? t("noMatchHint") : t("emptyHint")}
            />
          )
        }
        footer={
          <Pager
            hasPrevious={page.hasPrevious}
            hasNext={page.hasNext}
            onPrevious={page.previousPage}
            onNext={page.nextPage}
          />
        }
      />
    </div>
  );
}
