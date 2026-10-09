import { AdminDevNotice } from "@/admin/dev-notice";
import { can } from "@/auth/permissions";
import type { PageBodyProps } from "@/page/bodies";
import { InterviewsTable } from "./interviews-table";
import { TemplateForm } from "./template-form";
import { TemplatesTable } from "./templates-table";

/** The interviews pages' bodies (SP-06 templates, SP-07a interviews). Development sessions have
 * no account behind them, so they see the notice instead. */

export async function InterviewsBody({ session, params }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  const status = params.get("status");
  const group = status === "live" || status === "completed" ? status : "upcoming";
  return <InterviewsTable statusGroup={group} />;
}

export async function TemplatesBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  return <TemplatesTable canManage={can(session, "interviews.templates.manage")} />;
}

export async function NewTemplateBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <TemplateForm canManage />;
}
