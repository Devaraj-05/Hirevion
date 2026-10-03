import { AdminDevNotice } from "@/admin/dev-notice";
import type { PageBodyProps } from "@/page/bodies";
import { CandidatesTable } from "./candidates-table";

/** The candidates pages' bodies (SP-04b). Development sessions have no account behind them, so
 * they see the notice instead. */

export async function CandidatesBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <CandidatesTable />;
}
