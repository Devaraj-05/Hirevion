import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { CandidatePage } from "@/candidates/candidate-page";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";

export const generateMetadata = routeMetadata("/candidates/[id]");

/** One candidate: its own header (the candidate's name), so not a `guardedPage`. */
export default async function CandidateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/candidates/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("candidatesDetail")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  return <CandidatePage id={id} canManage={can(session, "candidates.manage")} />;
}
