import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { JobPage } from "@/jobs/job-page";
import { routeMetadata } from "@/page/guarded-page";

export const generateMetadata = routeMetadata("/jobs/[id]");

/** One job: its own header (the job's title), so not a `guardedPage`. */
export default async function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/jobs/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") return <AdminDevNotice />;
  const { id } = await params;
  return <JobPage id={id} canEdit={can(session, "jobs.create")} />;
}
