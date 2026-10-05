import { AdminDevNotice } from "@/admin/dev-notice";
import { can } from "@/auth/permissions";
import type { PageBodyProps } from "@/page/bodies";
import { QuestionLibrary } from "./library";

/** The question library's body (SP-06). Development sessions have no account behind them, so
 * they see the notice instead. */
export async function QuestionsBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  return <QuestionLibrary canManage={can(session, "questions.manage")} />;
}
