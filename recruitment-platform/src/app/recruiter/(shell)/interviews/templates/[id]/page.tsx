import { getTranslations } from "next-intl/server";
import { AdminDevNotice } from "@/admin/dev-notice";
import { Forbidden } from "@/auth/forbidden";
import { can } from "@/auth/permissions";
import { requireRoute } from "@/auth/server";
import { TemplatePage } from "@/interviews/template-page";
import { routeMetadata } from "@/page/guarded-page";
import { PageHeader } from "@/page/page-header";

export const generateMetadata = routeMetadata("/interviews/templates/[id]");

/** One template: its own header (the template's name), so not a `guardedPage`. */
export default async function TemplateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireRoute("/interviews/templates/[id]");
  if (!session) return <Forbidden />;
  if (session.source === "dev") {
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles("interviewTemplatesDetail")} />
        <AdminDevNotice />
      </>
    );
  }
  const { id } = await params;
  return <TemplatePage id={id} canManage={can(session, "interviews.templates.manage")} />;
}
