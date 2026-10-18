import { AdminDevNotice } from "@/admin/dev-notice";
import type { PageBodyProps } from "@/page/bodies";
import { PendingQueue } from "@/review/pending-queue";
import { ReportList } from "./report-list";

/** The reports section's list pages (SP-17). Development sessions have no account behind them,
 * so they see the notice instead. */

export async function InterviewReportsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <ReportList kind="interview" />;
}

export async function ProctoringReportsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <ReportList kind="proctoring" />;
}

export async function CandidateReportsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <ReportList kind="candidate" />;
}

export async function PendingReviewsBody({ session }: PageBodyProps) {
  return session.source === "dev" ? <AdminDevNotice /> : <PendingQueue />;
}
