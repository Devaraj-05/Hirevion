"use client";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Label,
  NativeSelect,
  SeverityBadge,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { type ProctorEvent, type ReviewOutcome, reviewEvent } from "@/interviews/proctoring-api";
import { getTranscript, sessionKeys } from "@/interviews/session-api";
import { getCodingReport, reportKeys } from "@/reports/api";
import { ReportView } from "@/reports/report-view";
import {
  addInterviewNote,
  getCandidate360,
  getProctoringEvents,
  listInterviewNotes,
  reviewKeys,
} from "./api";
import { clock, eventOffset } from "./sync";

const OUTCOMES: ReviewOutcome[] = ["confirmed", "false_positive", "not_relevant"];

/** The two-sided transcript (PRD §71 "view transcript"): each line is a button that moves the
 * player there, and the line being played is marked. */
export function TranscriptPanel({
  id,
  offset,
  onJump,
}: {
  id: string;
  offset: number;
  onJump: (ms: number) => void;
}) {
  const t = useTranslations("review.transcript");
  const speakers = useTranslations("interviews.proctoring.speaker");
  const transcript = useQuery({
    queryKey: sessionKeys.transcript(id),
    queryFn: () => getTranscript(id),
  });
  if (transcript.isPending) return <Skeleton className="h-40 w-full" />;
  const segments = transcript.data?.segments ?? [];
  const current = segments.reduce(
    (found, segment, index) => (segment.start_ms <= offset ? index : found),
    -1,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {segments.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("empty")}</p>
        ) : (
          <ol aria-label={t("title")} className="grid max-h-96 gap-1 overflow-y-auto text-sm">
            {segments.map((segment, index) => (
              <li key={segment.seq}>
                <button
                  type="button"
                  aria-current={index === current ? "true" : undefined}
                  onClick={() => onJump(segment.start_ms)}
                  aria-label={t("jump", {
                    time: clock(segment.start_ms),
                    speaker: speakers(segment.speaker),
                  })}
                  className={`flex w-full gap-2 rounded-md px-2 py-1 text-left hover:bg-surface-muted ${
                    index === current ? "bg-accent-subtle" : ""
                  }`}
                >
                  <span className="tabular-nums text-muted-foreground">
                    {clock(segment.start_ms)}
                  </span>
                  <span className="font-medium">{speakers(segment.speaker)}</span>
                  <span className="min-w-0 flex-1 break-words">{segment.text}</span>
                </button>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function EventReview({
  interviewId,
  event,
  onDone,
}: {
  interviewId: string;
  event: ProctorEvent;
  onDone: () => void;
}) {
  const t = useTranslations("review.events");
  const outcomes = useTranslations("interviews.proctoring.outcome");
  const problems = useAdminProblem();
  const id = useId();
  const [outcome, setOutcome] = useState<ReviewOutcome>("confirmed");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => reviewEvent(interviewId, event.id, outcome, reason.trim()),
    onSuccess: () => {
      toast.success(t("saved"), {});
      onDone();
    },
    onError: problems.show,
  });
  return (
    <div className="mt-2 grid gap-2 rounded-md border border-border p-3">
      <Label htmlFor={`${id}-outcome`}>{t("outcome")}</Label>
      <NativeSelect
        id={`${id}-outcome`}
        value={outcome}
        onChange={(e) => setOutcome(e.target.value as ReviewOutcome)}
        options={OUTCOMES.map((value) => ({ value, label: outcomes(value) }))}
      />
      <Label htmlFor={`${id}-reason`}>{t("reason")}</Label>
      <Textarea
        id={`${id}-reason`}
        rows={2}
        maxLength={1000}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div>
        <Button
          size="sm"
          disabled={save.isPending || reason.trim() === ""}
          onClick={() => save.mutate()}
        >
          {t("save")}
        </Button>
      </div>
    </div>
  );
}

/** The proctoring events (PRD §71 "review proctoring events") on the interview's timeline: each
 * can be jumped to and, for a reviewer, confirmed or dismissed with a reason. A dismissed event
 * stays here, marked. */
export function EventsPanel({
  id,
  anchor,
  canReview,
  onJump,
}: {
  id: string;
  anchor: string | null;
  canReview: boolean;
  onJump: (ms: number) => void;
}) {
  const t = useTranslations("review.events");
  const names = useTranslations("interviews.proctoring");
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const events = useInfiniteQuery({
    queryKey: reviewKeys.events(id),
    queryFn: ({ pageParam }) => getProctoringEvents(id, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  if (events.isPending) return <Skeleton className="h-32 w-full" />;
  const rows = events.data?.pages.flatMap((page) => page.events) ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 text-muted-foreground text-xs">{t("signals")}</p>
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("empty")}</p>
        ) : (
          <ul className="grid max-h-96 gap-2 overflow-y-auto">
            {rows.map((event) => {
              const at = eventOffset(anchor, event.started_at);
              const dismissed =
                event.review_status === "false_positive" || event.review_status === "not_relevant";
              const name = names.has(`events.${event.event}` as "events.FACE_ABSENT")
                ? names(`events.${event.event}` as "events.FACE_ABSENT")
                : event.event;
              return (
                <li
                  key={event.id}
                  className="grid gap-1 border-border border-b pb-2 text-sm last:border-b-0"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge
                      severity={event.severity}
                      label={names(`severity.${event.severity}`)}
                    />
                    <span
                      className={dismissed ? "text-muted-foreground line-through" : "font-medium"}
                    >
                      {name}
                    </span>
                    {at !== null ? (
                      <button
                        type="button"
                        className="min-h-6 min-w-6 tabular-nums underline"
                        aria-label={t("jump", { name, time: clock(at) })}
                        onClick={() => onJump(Math.max(0, at))}
                      >
                        {clock(at)}
                      </button>
                    ) : null}
                    {event.review_status !== "pending" ? (
                      <Badge tone={dismissed ? "neutral" : "info"}>
                        {names(`outcome.${event.review_status}`)}
                      </Badge>
                    ) : null}
                    {event.evidence_count > 0 ? (
                      <span className="text-muted-foreground text-xs">
                        {t("evidence", { count: event.evidence_count })}
                      </span>
                    ) : null}
                  </div>
                  {event.review ? (
                    <p className="text-muted-foreground text-xs">
                      {names("reviewedWith", { reason: event.review.reason })}
                    </p>
                  ) : null}
                  {canReview ? (
                    <div>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-expanded={open === event.id}
                        onClick={() => setOpen(open === event.id ? null : event.id)}
                      >
                        {t("review")}
                      </Button>
                      {open === event.id ? (
                        <EventReview
                          interviewId={id}
                          event={event}
                          onDone={() => {
                            setOpen(null);
                            void queryClient.invalidateQueries({ queryKey: reviewKeys.events(id) });
                          }}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {events.hasNextPage ? (
          <Button
            className="mt-2"
            size="sm"
            variant="secondary"
            disabled={events.isFetchingNextPage}
            onClick={() => void events.fetchNextPage()}
          >
            {t("more")}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Notes (PRD §71 "add notes"), optionally pinned to the moment being watched. */
export function NotesPanel({ id, offset }: { id: string; offset: number }) {
  const t = useTranslations("review.notes");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const field = useId();
  const [body, setBody] = useState("");
  const [pinned, setPinned] = useState(true);
  const notes = useQuery({ queryKey: reviewKeys.notes(id), queryFn: () => listInterviewNotes(id) });
  const add = useMutation({
    mutationFn: () =>
      addInterviewNote(id, {
        body: body.trim(),
        at_ms: pinned ? Math.max(0, Math.round(offset)) : null,
      }),
    onSuccess: () => {
      setBody("");
      toast.success(t("added"), {});
      void queryClient.invalidateQueries({ queryKey: reviewKeys.notes(id) });
    },
    onError: problems.show,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <form
          noValidate
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (body.trim()) add.mutate();
          }}
        >
          <Label htmlFor={field}>{t("label")}</Label>
          <Textarea
            id={field}
            rows={3}
            maxLength={4000}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
            {t("pin", { time: clock(offset) })}
          </label>
          <div>
            <Button type="submit" size="sm" disabled={add.isPending || body.trim() === ""}>
              {t("add")}
            </Button>
          </div>
        </form>
        {notes.data && notes.data.length > 0 ? (
          <ul className="grid gap-2 text-sm">
            {notes.data.map((note) => (
              <li key={note.id} className="grid gap-0.5 border-border border-t pt-2">
                <span className="text-muted-foreground text-xs">
                  {t("by", {
                    name: note.author_name,
                    when: format.dateTime(new Date(note.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                  })}
                  {note.at_ms !== null ? ` · ${t("at", { time: clock(note.at_ms) })}` : ""}
                </span>
                <span className="whitespace-pre-wrap break-words">{note.body}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** The screening result (PRD §71 "review screening result"): what the resume screening found for
 * the application this interview belongs to. */
export function ScreeningPanel({
  candidateId,
  applicationId,
}: {
  candidateId: string;
  applicationId: string;
}) {
  const t = useTranslations("review.screening");
  const overview = useQuery({
    queryKey: reviewKeys.candidate360(candidateId),
    queryFn: () => getCandidate360(candidateId),
  });
  const result = overview.data?.screening.find((item) => item.application_id === applicationId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm">
        {overview.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : result ? (
          <>
            <p className="font-medium">{t("score", { score: result.score })}</p>
            {[
              ["strengths", result.strengths],
              ["concerns", result.concerns],
              ["missing", result.missing],
            ].map(([key, items]) =>
              (items as string[]).length > 0 ? (
                <div key={key as string}>
                  <h3 className="font-medium text-xs uppercase tracking-wide text-muted-foreground">
                    {t(key as "strengths")}
                  </h3>
                  <ul className="list-disc pl-5">
                    {(items as string[]).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </>
        ) : (
          <p className="text-muted-foreground">{t("none")}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** The code the candidate saved and the test results (PRD §71 "review code" and "review test
 * results"). The coding service is SP-16, so the results say they are not there yet. */
export function CodePanel({ id }: { id: string }) {
  const t = useTranslations("review.code");
  const coding = useQuery({ queryKey: reportKeys.coding(id), queryFn: () => getCodingReport(id) });
  if (coding.isPending) return <Skeleton className="h-24 w-full" />;
  if (!coding.data) return null;
  const sections = coding.data.sections.filter((section) =>
    ["submitted_code", "test_results"].includes(section.key),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ReportView compact document={{ ...coding.data, sections }} />
      </CardContent>
    </Card>
  );
}
