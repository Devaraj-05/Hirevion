"use client";

import {
  Badge,
  DataTable,
  type DataTableColumn,
  EmptyState,
  Input,
  localViewStore,
} from "@hirevion/ui";
import { CalendarClock } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";
import {
  type InterviewSummary,
  interviewKeys,
  listInterviews,
  STATUS_TONES,
  type StatusGroup,
} from "./assigned-api";

const FILTERS = ["q"] as const;
const PAGE_SIZE = 25;
const candidateName = (interview: InterviewSummary) => interview.candidate.name;

/** The /interviews tabs (PRD §7): upcoming, live and completed interviews. */
export function InterviewsTable({ statusGroup }: { statusGroup: StatusGroup }) {
  const t = useTranslations("interviews.assigned");
  const statuses = useTranslations("interviews.assigned.statuses");
  const format = useFormatter();
  const labels = useTableLabels(candidateName);
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");
  const query = { status_group: statusGroup, q: filters.q || undefined } as const;
  const page = useCursorPage([...interviewKeys.list, query], (cursor) =>
    listInterviews({ ...query, cursor, limit: PAGE_SIZE }),
  );

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const columns = useMemo<DataTableColumn<InterviewSummary>[]>(
    () => [
      {
        id: "candidate",
        header: t("candidate"),
        hideable: false,
        cell: (interview) => (
          <Link
            href={`/interviews/${interview.id}`}
            aria-label={t("open", { name: interview.candidate.name })}
            className="grid hover:underline focus-visible:underline"
          >
            <span className="font-medium">{interview.candidate.name}</span>
            <span className="text-muted-foreground text-xs">{interview.reference}</span>
          </Link>
        ),
      },
      { id: "job", header: t("job"), cell: (interview) => interview.job_title },
      {
        id: "window",
        header: t("window"),
        cell: (interview) =>
          format.dateTimeRange(new Date(interview.starts_at), new Date(interview.expires_at), {
            dateStyle: "medium",
            timeStyle: "short",
          }),
      },
      {
        id: "duration",
        header: t("duration"),
        cell: (interview) => t("minutes", { minutes: interview.duration_minutes }),
      },
      {
        id: "status",
        header: t("status"),
        cell: (interview) => (
          <Badge tone={STATUS_TONES[interview.status]}>{statuses(interview.status)}</Badge>
        ),
      },
    ],
    [t, statuses, format],
  );

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={submitSearch} className="max-w-md">
        <Input
          type="search"
          aria-label={t("search")}
          placeholder={t("search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </form>
      <DataTable
        tableId={`interviews-${statusGroup}`}
        caption={t(`caption.${statusGroup}`)}
        columns={columns}
        rows={page.rows}
        getRowId={(interview) => interview.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : (
            <EmptyState
              icon={<CalendarClock />}
              title={query.q ? t("noMatchTitle") : t(`empty.${statusGroup}`)}
              description={query.q ? t("noMatchHint") : t("emptyHint")}
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
