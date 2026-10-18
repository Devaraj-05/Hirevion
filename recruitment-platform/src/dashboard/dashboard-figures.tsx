"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { getDashboard, interviewKeys } from "@/interviews/assigned-api";
import { KpiGrid } from "./kpi-grid";
import { DASHBOARD_FILTERS, type Kpi } from "./model";

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
    if (value === undefined || name === "candidateStatus") continue;
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
  const values: Partial<Record<Kpi, number>> = figures.data
    ? {
        interviewsScheduled: figures.data.interviews_scheduled,
        liveInterviews: figures.data.live_interviews,
        completedInterviews: figures.data.completed_interviews,
        pendingReviews: figures.data.pending_reviews,
      }
    : {};
  return <KpiGrid values={values} />;
}
