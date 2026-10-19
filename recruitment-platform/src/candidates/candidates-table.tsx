"use client";

import {
  DataTable,
  type DataTableColumn,
  EmptyState,
  Input,
  localViewStore,
  NativeSelect,
} from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { UsersRound } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { Pager } from "@/data/pager";
import { QueryFailed } from "@/data/query-failed";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { listJobs } from "@/jobs/api";
import { useTableLabels } from "@/page/use-table-labels";
import { type CandidateSummary, listCandidates, type StageGroup } from "./api";
import { FlagBadges } from "./flags";
import { keys } from "./queries";

const FILTERS = ["stage", "q", "job"] as const;
const PAGE_SIZE = 25;
const JOB_OPTIONS = 100;
const candidateName = (candidate: CandidateSummary) => candidate.name;

/** The organisation's candidates the reader reaches (PRD §19), newest first. The stage tabs
 * filter by application stage, the interview and completed ones included. */
export function CandidatesTable() {
  const t = useTranslations("candidates.table");
  const format = useFormatter();
  const labels = useTableLabels(candidateName);
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");
  const stage = (filters.stage || undefined) as StageGroup | undefined;
  const jobs = useQuery({
    queryKey: ["jobs", "list", "options"],
    queryFn: () => listJobs({ limit: JOB_OPTIONS }),
    retry: false,
  });
  const query = {
    q: filters.q || undefined,
    job_id: filters.job || undefined,
    stage_group: stage,
  };
  const page = useCursorPage([...keys.list, query], (cursor) =>
    listCandidates({ ...query, cursor, limit: PAGE_SIZE }),
  );

  const columns = useMemo<DataTableColumn<CandidateSummary>[]>(
    () => [
      {
        id: "name",
        header: t("name"),
        hideable: false,
        cell: (candidate) => (
          <div className="grid gap-1">
            <Link
              href={`/candidates/${candidate.id}`}
              aria-label={t("open", { name: candidate.name })}
              className="grid hover:underline focus-visible:underline"
            >
              <span className="font-medium">{candidate.name}</span>
              {candidate.email ? (
                <span className="text-muted-foreground text-xs">{candidate.email}</span>
              ) : null}
            </Link>
            <FlagBadges flags={candidate.flags} />
          </div>
        ),
      },
      { id: "headline", header: t("headline"), cell: (candidate) => candidate.headline ?? "—" },
      { id: "location", header: t("location"), cell: (candidate) => candidate.location ?? "—" },
      {
        id: "skills",
        header: t("skills"),
        cell: (candidate) => candidate.skills.join(", ") || "—",
      },
      {
        id: "updated",
        header: t("updated"),
        cell: (candidate) =>
          format.dateTime(new Date(candidate.updated_at), { dateStyle: "medium" }),
      },
    ],
    [t, format],
  );

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const filtered = Boolean(query.q || query.job_id);
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
          aria-label={t("job")}
          className="w-64"
          value={filters.job ?? ""}
          onChange={(event) => setFilters({ ...filters, job: event.target.value })}
          options={[
            { value: "", label: t("anyJob") },
            ...(jobs.data?.items ?? []).map((job) => ({
              value: job.id,
              label: `${job.reference} · ${job.title}`,
            })),
          ]}
        />
      </div>
      <DataTable
        tableId="candidates"
        caption={t("caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(candidate) => candidate.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : page.error ? (
            <QueryFailed onRetry={page.refetch} />
          ) : (
            <EmptyState
              icon={<UsersRound />}
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
