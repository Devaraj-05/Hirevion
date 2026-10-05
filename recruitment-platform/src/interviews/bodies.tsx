import { AdminDevNotice } from "@/admin/dev-notice";
import { can } from "@/auth/permissions";
import type { PageBodyProps } from "@/page/bodies";
import { TemplateForm } from "./template-form";
import { TemplatesTable } from "./templates-table";

/** The interview templates pages' bodies (SP-06). Development sessions have no account behind
 * them, so they see the notice instead. */

export async function TemplatesBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  return <TemplatesTable canManage={can(session, "interviews.templates.manage")} />;
}

export async function NewTemplateBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <TemplateForm canManage />;
}
