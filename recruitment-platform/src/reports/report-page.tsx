"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Skeleton,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileX } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useAdminProblem } from "@/admin/problems";
import { PageHeader } from "@/page/page-header";
import {
  createExport,
  downloadHref,
  getCandidateReport,
  getCodingReport,
  getInterviewReport,
  getProctoringReport,
  listExports,
  type ReportDocument,
  type ReportKind,
  reportKeys,
} from "./api";
import { ReportView } from "./report-view";

type Shown = "interview" | "proctoring" | "coding" | "candidate";

const LOADERS: Record<Shown, (id: string) => Promise<ReportDocument>> = {
  interview: getInterviewReport,
  proctoring: getProctoringReport,
  coding: getCodingReport,
  candidate: getCandidateReport,
};
const KEYS: Record<Shown, (id: string) => readonly unknown[]> = {
  interview: reportKeys.interview,
  proctoring: reportKeys.proctoring,
  coding: reportKeys.coding,
  candidate: reportKeys.candidate,
};

/** One report (PRD §68, §69, §99) as a web view, with its PDF: `canExport` shows the export button
 * and the PDFs already made. The API checks every permission again, and viewing and downloading
 * are audited there. */
export function ReportPage({
  kind,
  id,
  canExport,
  canReview = false,
}: {
  kind: Shown;
  id: string;
  canExport: boolean;
  canReview?: boolean;
}) {
  const t = useTranslations("reports");
  const report = useQuery({ queryKey: KEYS[kind](id), queryFn: () => LOADERS[kind](id) });
  const forCandidate = kind === "candidate";

  if (report.isPending) return <Skeleton className="h-64 w-full" />;
  if (report.isError || !report.data) {
    const missing = isApiProblem(report.error) && report.error.status === 404;
    return (
      <EmptyState
        icon={<FileX />}
        title={missing ? t("page.notFound") : t("page.loadFailed")}
        description={missing ? t("page.notFoundHint") : t("page.loadFailedHint")}
      />
    );
  }
  const document = report.data;
  const interviewId = document.subject.interview_id ?? null;
  return (
    <>
      <Link
        href={`/reports/${kind === "coding" ? "interview" : kind}`}
        className="mb-2 inline-flex items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t(`page.back.${kind}`)}
      </Link>
      <PageHeader
        title={document.title}
        description={document.subtitle}
        actions={canExport ? <ExportButton kind={kind} id={id} /> : null}
      />
      {!forCandidate && interviewId ? (
        <nav aria-label={t("page.related")} className="mb-4 flex flex-wrap gap-3 text-sm">
          {(["interview", "proctoring", "coding"] as const)
            .filter((other) => other !== kind)
            .map((other) => (
              <Link key={other} href={`/reports/${other}/${interviewId}`} className="underline">
                {t(`page.open.${other}`)}
              </Link>
            ))}
          {canReview ? (
            <Link href={`/interviews/${interviewId}/review`} className="underline">
              {t("page.openReview")}
            </Link>
          ) : null}
        </nav>
      ) : null}
      <div className="grid gap-6">
        <ReportView document={document} />
        {canExport ? <Exports kind={kind} id={id} /> : null}
      </div>
    </>
  );
}

function subjectOf(kind: Shown, id: string) {
  return kind === "candidate" ? { candidateId: id } : { interviewId: id };
}

function ExportButton({ kind, id }: { kind: Shown; id: string }) {
  const t = useTranslations("reports");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const exporting = useMutation({
    mutationFn: () =>
      createExport({
        kind: kind as ReportKind,
        ...(kind === "candidate" ? { candidate_id: id } : { interview_id: id }),
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: reportKeys.exports(`${kind}:${id}`) });
      toast.success(t("exports.made"), {});
      // The file is fetched by the browser, so the download is an audited GET.
      window.location.assign(downloadHref(made.id));
    },
    onError: (error) => {
      if (isApiProblem(error) && error.code === "pdf-unavailable") {
        toast.error(t("exports.unavailable"), {});
      } else problems.show(error);
    },
  });
  return (
    <Button disabled={exporting.isPending} onClick={() => exporting.mutate()}>
      <Download aria-hidden className="size-4" />
      {exporting.isPending ? t("exports.exporting") : t("exports.export")}
    </Button>
  );
}

function Exports({ kind, id }: { kind: Shown; id: string }) {
  const t = useTranslations("reports.exports");
  const format = useFormatter();
  const exported = useQuery({
    queryKey: reportKeys.exports(`${kind}:${id}`),
    queryFn: () => listExports(subjectOf(kind, id)),
  });
  const mine = (exported.data ?? []).filter((item) => item.kind === kind);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {mine.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        ) : (
          <ul className="grid gap-2 text-sm">
            {mine.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  {t("line", {
                    when: format.dateTime(new Date(item.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                    who: item.requested_by_name ?? t("someone"),
                    size: format.number(Math.max(1, Math.round(item.bytes / 1024))),
                  })}
                </span>
                <a href={downloadHref(item.id)} className="underline">
                  {t("download")}
                </a>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-muted-foreground text-xs">{t("audited")}</p>
      </CardContent>
    </Card>
  );
}
