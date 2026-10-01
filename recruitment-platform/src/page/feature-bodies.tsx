import { DashboardFilters } from "@/dashboard/dashboard-filters";
import { KpiGrid } from "@/dashboard/kpi-grid";
import { PipelineBoard } from "@/dashboard/pipeline-board";
import { JobsTable } from "@/jobs/jobs-table";

/** Page bodies built from feature components; their data arrives with the owning sub-projects. */

export function DashboardBody() {
  return (
    <div className="flex flex-col gap-6">
      <DashboardFilters />
      <KpiGrid values={{}} />
      <PipelineBoard columns={{}} />
    </div>
  );
}

export function JobsBody() {
  return <JobsTable />;
}
