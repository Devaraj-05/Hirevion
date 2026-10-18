"use client";

import { Badge, EmptyState, Skeleton } from "@hirevion/ui";
import { FileText } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { listCandidates } from "@/candidates/api";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import { interviewKeys, listInterviews, STATUS_TONES } from "@/interviews/assigned-api";

const PAGE_SIZE = 25;

/** The reports section's lists (PRD §7): finished interviews for the interview and proctoring
 * reports, and candidates for the internal candidate report. Each row opens its report. */
export function ReportList({ kind }: { kind: "interview" | "proctoring" | "candidate" }) {
  return kind === "candidate" ? <CandidateRows /> : <InterviewRows kind={kind} />;
}

function InterviewRows({ kind }: { kind: "interview" | "proctoring" }) {
  const t = useTranslations("reports.list");
  const statuses = useTranslations("interviews.assigned.statuses");
  const format = useFormatter();
  const page = useCursorPage([...interviewKeys.list, "reports"], (cursor) =>
    listInterviews({ status_group: "completed", cursor, limit: PAGE_SIZE }),
  );
  if (page.isLoading) return <Skeleton className="h-40 w-full" />;
  if (page.rows.length === 0) {
    return (
      <EmptyState
        icon={<FileText />}
        title={t("noInterviews")}
        description={t("noInterviewsHint")}
      />
    );
  }
  return (
    <div className="grid gap-3">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t(`caption.${kind}`)}</caption>
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("candidate")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("job")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("interview")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("status")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("opened")}
              </th>
            </tr>
          </thead>
          <tbody>
            {page.rows.map((interview) => (
              <tr key={interview.id} className="border-border border-t">
                <td className="px-3 py-2">
                  <Link
                    href={`/reports/${kind}/${interview.id}`}
                    aria-label={t("open", { name: interview.candidate.name })}
                    className="inline-flex min-h-6 items-center font-medium hover:underline"
                  >
                    {interview.candidate.name}
                  </Link>
                </td>
                <td className="px-3 py-2">{interview.job_title}</td>
                <td className="px-3 py-2">{interview.reference}</td>
                <td className="px-3 py-2">
                  <Badge tone={STATUS_TONES[interview.status]}>{statuses(interview.status)}</Badge>
                </td>
                <td className="px-3 py-2">
                  {format.dateTime(new Date(interview.starts_at), { dateStyle: "medium" })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        hasPrevious={page.hasPrevious}
        hasNext={page.hasNext}
        onPrevious={page.previousPage}
        onNext={page.nextPage}
      />
    </div>
  );
}

function CandidateRows() {
  const t = useTranslations("reports.list");
  const page = useCursorPage(["candidates", "list", "reports"], (cursor) =>
    listCandidates({ cursor, limit: PAGE_SIZE }),
  );
  if (page.isLoading) return <Skeleton className="h-40 w-full" />;
  if (page.rows.length === 0) {
    return (
      <EmptyState
        icon={<FileText />}
        title={t("noCandidates")}
        description={t("noCandidatesHint")}
      />
    );
  }
  return (
    <div className="grid gap-3">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("caption.candidate")}</caption>
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("candidate")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("headline")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("view360")}
              </th>
            </tr>
          </thead>
          <tbody>
            {page.rows.map((candidate) => (
              <tr key={candidate.id} className="border-border border-t">
                <td className="px-3 py-2">
                  <Link
                    href={`/reports/candidate/${candidate.id}`}
                    aria-label={t("open", { name: candidate.name })}
                    className="inline-flex min-h-6 items-center font-medium hover:underline"
                  >
                    {candidate.name}
                  </Link>
                </td>
                <td className="px-3 py-2">{candidate.headline ?? ""}</td>
                <td className="px-3 py-2">
                  <Link
                    href={`/candidates/${candidate.id}`}
                    className="inline-flex min-h-6 items-center underline"
                  >
                    {t("view360")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        hasPrevious={page.hasPrevious}
        hasNext={page.hasNext}
        onPrevious={page.previousPage}
        onNext={page.nextPage}
      />
    </div>
  );
}
