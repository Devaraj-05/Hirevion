import { AdminDevNotice } from "@/admin/dev-notice";
import { can } from "@/auth/permissions";
import type { PageBodyProps } from "@/page/bodies";
import { CandidatesTable } from "./candidates-table";
import { CandidateRequestsTable } from "./requests-table";

/** The candidates pages' bodies (SP-04b). Development sessions have no account behind them, so
 * they see the notice instead. */

export async function CandidatesBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <CandidatesTable />;
}

/** Candidates' requests from the portal (SP-07b). */
export async function CandidateRequestsBody({ session }: PageBodyProps) {
  if (session.source === "dev") return <AdminDevNotice />;
  return <CandidateRequestsTable canManage={can(session, "candidates.requests.manage")} />;
}
