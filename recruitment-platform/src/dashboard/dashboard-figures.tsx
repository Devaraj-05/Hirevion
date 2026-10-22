"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { QueryFailed } from "@/data/query-failed";
import { getDashboard, interviewKeys } from "@/interviews/assigned-api";
import { KpiGrid } from "./kpi-grid";
import { DASHBOARD_FILTERS, KPIS, type Kpi } from "./model";

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A `YYYY-MM-DD` filter as the instant its day starts in the reader's time zone, or undefined
 * for anything that isn't a real date (an edited or mistyped link). */
function dayStart(value: string, addDays = 0): string | undefined {
  if (!DATE.test(value)) return undefined;
  const day = new Date(`${value}T00:00:00`);
  if (Number.isNaN(day.getTime())) return undefined;
  day.setDate(day.getDate() + addDays);
  return day.toISOString();
}

/** The page's filters as the API takes them: the date range from the start of `from` to the end
 * of `to` (inclusive) in the reader's time zone; the rest as they are. */
export function dashboardQuery(params: URLSearchParams): Record<string, string | undefined> {
  const query: Record<string, string | undefined> = {};
  for (const name of DASHBOARD_FILTERS) {
    const value = params.get(name) || undefined;
    if (value === undefined) continue;
    if (name === "from") query.from = dayStart(value);
    else if (name === "to") query.to = dayStart(value, 1);
    else query[name] = value;
  }
  return query;
}

/** The figures the API has data for, under the page's filters; the others show "no data yet". */
export function DashboardFigures({ live }: { live: boolean }) {
  const params = useSearchParams();
  const query = dashboardQuery(new URLSearchParams(params.toString()));
  const figures = useQuery({
    queryKey: [...interviewKeys.dashboard, query],
    queryFn: () => getDashboard(query),
    enabled: live,
  });
  if (figures.isError) return <QueryFailed onRetry={() => void figures.refetch()} />;
  // A figure the reader may not read comes back null: it stays "no data yet".
  const data = figures.data;
  const values: Partial<Record<Kpi, number>> = {};
  if (data) {
    const all: Record<Kpi, number | null | undefined> = {
      openJobs: data.open_jobs,
      activeCandidates: data.active_candidates,
      screened: data.screened,
      shortlisted: data.shortlisted,
      inPipeline: data.in_pipeline,
      interviewsScheduled: data.interviews_scheduled,
      liveInterviews: data.live_interviews,
      completedInterviews: data.completed_interviews,
      pendingReviews: data.pending_reviews,
      proctoringAlerts: data.proctoring_alerts,
    };
    for (const kpi of KPIS) {
      const value = all[kpi];
      if (typeof value === "number") values[kpi] = value;
    }
  }
  return <KpiGrid values={values} />;
}
