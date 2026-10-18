import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";
import { ReportPage } from "@/reports/report-page";

export const generateMetadata = routeMetadata("/reports/candidate/[id]");

/** One candidate's internal report: its own header, so not a `guardedPage`. */
export default async function CandidateReportPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/reports/candidate/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("reportsCandidateDetail")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  return <ReportPage kind="candidate" id={id} canExport={can(session, "reports.export")} />;
}
