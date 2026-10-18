import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";
import { ReportPage } from "@/reports/report-page";

export const generateMetadata = routeMetadata("/reports/coding/[id]");

/** One interview's coding report: its own header, so not a `guardedPage`. */
export default async function CodingReportPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/reports/coding/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("reportsCodingDetail")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  return (
    <ReportPage
      kind="coding"
      id={id}
      canExport={can(session, "reports.export")}
      canReview={can(session, "reports.interview.view")}
    />
  );
}
