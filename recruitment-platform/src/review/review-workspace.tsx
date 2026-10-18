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
import { ArrowLeft, SearchX } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { getInterview, interviewKeys } from "@/interviews/assigned-api";
import { EvaluationCard } from "@/interviews/evaluation-card";
import { PageHeader } from "@/page/page-header";
import { createExport, downloadHref, type ReportKind, reportKeys } from "@/reports/api";
import { CandidateReportCard } from "@/reports/candidate-report-card";
import { getReviewMedia, reviewKeys } from "./api";
import { HiringPanel } from "./hiring-panel";
import { EvidenceJumpContext } from "./jump-context";
import { CodePanel, EventsPanel, NotesPanel, ScreeningPanel, TranscriptPanel } from "./panels";
import { MediaPlayer } from "./player";
import { ScoresPanel } from "./scores-panel";
import { timelineEnd } from "./sync";

export interface ReviewAccess {
  /** `reports.proctoring.view`: the events and the proctoring report. */
  events: boolean;
  /** `interviews.manage` as well: confirming or dismissing events. */
  reviewEvents: boolean;
  /** `reports.score.modify`. */
  modifyScores: boolean;
  /** `reports.export`. */
  export: boolean;
  /** `reports.release`. */
  release: boolean;
  /** `reports.candidate.view`: the candidate-visible report. */
  candidateReport: boolean;
  /** `candidates.view`: the screening result and the hiring workflow. */
  candidate: boolean;
  /** `hiring.input`. */
  input: boolean;
  /** `admin.ai.manage` and `reports.analytics.view`, for the evaluation card's extras. */
  rerun: boolean;
  measure: boolean;
}

/**
 * The review workspace (PRD §71): one interview on one timeline. The recordings play together;
 * the transcript, the proctoring events and the evaluation's evidence move them; notes, score
 * changes, the hiring status and the decision, and the exports are beside them. Everything the
 * API refuses a reader is left out.
 */
export function ReviewWorkspace({ id, access }: { id: string; access: ReviewAccess }) {
  const t = useTranslations("review");
  const queryClient = useQueryClient();
  // `?t=<ms>` opens the workspace at a moment (the activity timeline links to them).
  const start = Number(useSearchParams().get("t"));
  const [offset, setOffset] = useState(Number.isFinite(start) && start > 0 ? start : 0);
  const [playing, setPlaying] = useState(false);
  const [seekRevision, setSeekRevision] = useState(0);

  const interview = useQuery({
    queryKey: interviewKeys.detail(id),
    queryFn: () => getInterview(id),
  });
  const media = useQuery({
    queryKey: reviewKeys.media(id),
    queryFn: () => getReviewMedia(id),
    enabled: interview.isSuccess,
    // The links last five minutes: ask again only when a file stops loading.
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });

  const jump = useCallback((ms: number) => {
    setOffset(Math.max(0, ms));
    setSeekRevision((revision) => revision + 1);
  }, []);
  const expired = useCallback(() => {
    void media.refetch().then(() => setSeekRevision((revision) => revision + 1));
  }, [media]);

  const end = useMemo(() => {
    const tracks = (media.data?.tracks ?? []).map((track) => ({
      started_at: track.started_at ?? null,
      duration_ms: track.duration_ms ?? null,
      timeline: track.timeline ?? null,
    }));
    return timelineEnd(media.data?.anchor ?? null, tracks, 0);
  }, [media.data]);

  if (interview.isPending) return <Skeleton className="h-64 w-full" />;
  if (interview.isError || !interview.data) {
    const missing = isApiProblem(interview.error) && interview.error.status === 404;
    return (
      <EmptyState
        icon={<SearchX />}
        title={missing ? t("notFound") : t("loadFailed")}
        description={missing ? t("notFoundHint") : t("loadFailedHint")}
      />
    );
  }
  const data = interview.data;
  const anchor = media.data?.anchor ?? data.started_at ?? null;
  return (
    <EvidenceJumpContext.Provider value={jump}>
      <Link
        href={`/interviews/${id}`}
        className="mb-2 inline-flex items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("back")}
      </Link>
      <PageHeader
        title={t("pageTitle", { name: data.candidate.name, reference: data.reference })}
        description={data.job_title}
        actions={
          <>
            <Button asChild variant="secondary" size="sm">
              <Link href={`/reports/interview/${id}`}>{t("openReport")}</Link>
            </Button>
            {access.events ? (
              <Button asChild variant="secondary" size="sm">
                <Link href={`/reports/proctoring/${id}`}>{t("openProctoring")}</Link>
              </Button>
            ) : null}
          </>
        }
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="grid min-w-0 gap-4 self-start">
          {media.isPending ? (
            <Skeleton className="h-64 w-full" />
          ) : media.data ? (
            <MediaPlayer
              media={media.data}
              offset={offset}
              playing={playing}
              seekRevision={seekRevision}
              end={end}
              onOffset={setOffset}
              onSeek={jump}
              onPlayingChange={setPlaying}
              onExpired={expired}
            />
          ) : (
            <Card>
              <CardContent className="pt-6 text-muted-foreground text-sm">
                {t("mediaFailed")}
              </CardContent>
            </Card>
          )}
          <TranscriptPanel id={id} offset={offset} onJump={jump} />
          <EvaluationCard id={id} canRerun={access.rerun} canMeasure={access.measure} />
          <ScoresPanel id={id} canModify={access.modifyScores} />
          <CodePanel id={id} />
        </div>
        <div className="grid min-w-0 gap-4 self-start">
          {access.candidate ? (
            <HiringPanel
              applicationId={data.application_id}
              canInput={access.input}
              onChanged={() => {
                void queryClient.invalidateQueries({ queryKey: interviewKeys.detail(id) });
              }}
            />
          ) : null}
          {access.events ? (
            <EventsPanel id={id} anchor={anchor} canReview={access.reviewEvents} onJump={jump} />
          ) : null}
          <NotesPanel id={id} offset={offset} />
          {access.candidate ? (
            <ScreeningPanel candidateId={data.candidate.id} applicationId={data.application_id} />
          ) : null}
          {access.export ? <ExportCard id={id} canProctoring={access.events} /> : null}
          {access.candidateReport ? (
            <CandidateReportCard id={id} canRelease={access.release} />
          ) : null}
        </div>
      </div>
    </EvidenceJumpContext.Provider>
  );
}

/** Exporting the reports (PRD §71 "export reports"): a PDF of each, downloaded as it is made.
 * Each export and each download is audited. */
function ExportCard({ id, canProctoring }: { id: string; canProctoring: boolean }) {
  const t = useTranslations("review.export");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const kinds: ReportKind[] = canProctoring
    ? ["interview", "proctoring", "coding"]
    : ["interview", "coding"];
  const exporting = useMutation({
    mutationFn: (kind: ReportKind) => createExport({ kind, interview_id: id }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: reportKeys.exports(`${made.kind}:${id}`) });
      toast.success(t("made"), {});
      window.location.assign(downloadHref(made.id));
    },
    onError: (error) => {
      if (isApiProblem(error) && error.code === "pdf-unavailable")
        toast.error(t("unavailable"), {});
      else problems.show(error);
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        <p className="text-muted-foreground text-sm">{t("hint")}</p>
        <ul className="flex flex-wrap gap-2">
          {kinds.map((kind) => (
            <li key={kind}>
              <Button
                size="sm"
                variant="secondary"
                disabled={exporting.isPending}
                onClick={() => exporting.mutate(kind)}
              >
                {t(`kinds.${kind as "interview"}`)}
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
