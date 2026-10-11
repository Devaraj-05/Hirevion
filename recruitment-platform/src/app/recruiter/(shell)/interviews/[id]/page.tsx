import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { InterviewPage } from "@/interviews/interview-page";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";

export const generateMetadata = routeMetadata("/interviews/[id]");

/** One interview: its own header (the candidate's name), so not a `guardedPage`. */
export default async function InterviewDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/interviews/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("interviewsDetail")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  return (
    <InterviewPage
      id={id}
      canManage={can(session, "interviews.manage")}
      canReview={can(session, "reports.interview.view")}
      canRerun={can(session, "admin.ai.manage")}
      canMeasure={can(session, "reports.analytics.view")}
    />
  );
}
