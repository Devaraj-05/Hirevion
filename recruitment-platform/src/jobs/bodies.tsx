import { AdminDevNotice } from "@/admin/dev-notice";
import { can } from "@/auth/permissions";
import type { PageBodyProps } from "@/page/bodies";
import { JobForm } from "./job-form";
import { JobsTable } from "./jobs-table";

/** The jobs pages' bodies (SP-04a). Development sessions have no account behind them, so they
 * see the notice instead. */

export async function JobsBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  return <JobsTable canCreate={can(session, "jobs.create")} />;
}

export async function NewJobBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <JobForm />;
}
