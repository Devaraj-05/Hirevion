import { DashboardFigures } from "@/dashboard/dashboard-figures";
import { DashboardFilters } from "@/dashboard/dashboard-filters";
import { PipelineBoard } from "@/dashboard/pipeline-board";
import type { PageBodyProps } from "./bodies";

/** Page bodies built from feature components; their data arrives with the owning sub-projects. */

export function DashboardBody({ session }: PageBodyProps) {
  return (
    <div className="flex flex-col gap-6">
      <DashboardFilters />
      <DashboardFigures live={session.source !== "dev"} />
      <PipelineBoard columns={{}} />
    </div>
  );
}
