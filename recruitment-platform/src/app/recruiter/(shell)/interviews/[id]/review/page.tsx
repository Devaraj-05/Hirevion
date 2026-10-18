import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";
import { ReviewWorkspace } from "@/review/review-workspace";

export const generateMetadata = routeMetadata("/interviews/[id]/review");

/** The review workspace for one interview: its own header (the candidate's name), so not a
 * `guardedPage`. */
export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/interviews/[id]/review");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("interviewsReview")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  const events = can(session, "reports.proctoring.view");
  return (
    <ReviewWorkspace
      id={id}
      access={{
        events,
        reviewEvents: events && can(session, "interviews.manage"),
        modifyScores: can(session, "reports.score.modify"),
        export: can(session, "reports.export"),
        release: can(session, "reports.release"),
        candidateReport: can(session, "reports.candidate.view"),
        candidate: can(session, "candidates.view"),
        input: can(session, "hiring.input"),
        rerun: can(session, "admin.ai.manage"),
        measure: can(session, "reports.analytics.view"),
      }}
    />
  );
}
