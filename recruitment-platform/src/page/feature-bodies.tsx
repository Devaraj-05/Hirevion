import { can } from "@/auth/permissions";
import { DashboardFigures } from "@/dashboard/dashboard-figures";
import { DashboardFilters } from "@/dashboard/dashboard-filters";
import { LivePipeline } from "@/dashboard/live-pipeline";
import { PipelineBoard } from "@/dashboard/pipeline-board";
import type { PageBodyProps } from "./bodies";

/** Page bodies built from feature components; their data arrives with the owning sub-projects. */

export function DashboardBody({ session }: PageBodyProps) {
  const live = session.source !== "dev";
  return (
    <div className="flex flex-col gap-6">
      <DashboardFilters />
      <DashboardFigures live={live} />
      {live && can(session, "candidates.view") ? <LivePipeline /> : <PipelineBoard columns={{}} />}
    </div>
  );
}
