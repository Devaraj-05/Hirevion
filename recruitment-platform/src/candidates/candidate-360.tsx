"use client";

import { Badge, Button, Label, SeverityBadge, Skeleton, Textarea, toast } from "@hirevion/ui";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type ReactNode, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { downloadHref } from "@/reports/api";
import {
  addCandidateNote,
  type Candidate360,
  getCandidate360,
  getHiringState,
  getTimeline,
  type InterviewHistoryItem,
  reviewKeys,
  TIMELINE_SOURCES,
  type TimelineSource,
} from "@/review/api";
import { MoveDialog } from "@/review/hiring-panel";
import { clock } from "@/review/sync";

/** Loads Candidate 360's data once for the tabs that read it. */
export function useCandidate360(id: string) {
  return useQuery({ queryKey: reviewKeys.candidate360(id), queryFn: () => getCandidate360(id) });
}

function Table({
  caption,
  columns,
  children,
}: {
  caption: string;
  columns: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-muted">
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col" className="px-3 py-2 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground text-sm">{children}</p>;
}

function useScore() {
  const format = useFormatter();
  return (value: number | null | undefined) =>
    value === null || value === undefined
      ? "—"
      : format.number(value, { maximumFractionDigits: 1 });
}

function ScoreText({ value }: { value: { ai: number | null; value: number | null } | null }) {
  const t = useTranslations("candidate360");
  const score = useScore();
  if (!value) return <span>{t("noScore")}</span>;
  return (
    <span>
      {value.value !== value.ai
        ? t("adjusted", { score: score(value.value), ai: score(value.ai) })
        : score(value.value)}
    </span>
  );
}

/** Screening (PRD §20): what the resume screening found for each job applied to. */
export function ScreeningTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.screening");
  const format = useFormatter();
  if (data.screening.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <div className="grid max-w-3xl gap-4">
      {data.screening.map((item) => (
        <section
          key={item.application_id}
          aria-label={item.job_title}
          className="grid gap-2 rounded-lg border border-border p-4 text-sm"
        >
          <h3 className="font-semibold text-base">{item.job_title}</h3>
          <p>
            {t("score", { score: item.score })}
            {item.rank ? ` · ${t("rank", { rank: item.rank })}` : ""}
            {` · ${t("when", { when: format.dateTime(new Date(item.screened_at), { dateStyle: "medium" }) })}`}
          </p>
          {(["strengths", "concerns", "missing", "knockouts"] as const).map((key) =>
            item[key].length > 0 ? (
              <div key={key}>
                <h4 className="text-muted-foreground text-xs uppercase tracking-wide">{t(key)}</h4>
                <ul className="list-disc pl-5">
                  {item[key].map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
        </section>
      ))}
    </div>
  );
}

/** Interview history: every interview with its status, hiring status and scores. */
export function InterviewHistoryTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.history");
  const statuses = useTranslations("interviews.assigned.statuses");
  const hiring = useTranslations("hiring.statuses");
  const format = useFormatter();
  if (data.interviews.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <Table
      caption={t("caption")}
      columns={[
        t("interview"),
        t("job"),
        t("status"),
        t("hiring"),
        t("date"),
        t("overall"),
        t("flags"),
      ]}
    >
      {data.interviews.map((item) => (
        <tr key={item.interview_id} className="border-border border-t align-top">
          <td className="px-3 py-2">
            <Link href={`/interviews/${item.interview_id}`} className="font-medium hover:underline">
              {item.reference}
            </Link>
            <span className="block text-muted-foreground text-xs">{item.template_name}</span>
          </td>
          <td className="px-3 py-2">{item.job_title}</td>
          <td className="px-3 py-2">
            <Badge>{statuses(item.status as "completed")}</Badge>
          </td>
          <td className="px-3 py-2">{hiring(item.hiring_status)}</td>
          <td className="px-3 py-2">
            {item.started_at
              ? format.dateTime(new Date(item.started_at), { dateStyle: "medium" })
              : "—"}
          </td>
          <td className="px-3 py-2">
            <ScoreText value={item.evaluation.overall} />
          </td>
          <td className="px-3 py-2">{item.evaluation.flags.join(", ") || "—"}</td>
        </tr>
      ))}
    </Table>
  );
}

/** Technical skills: what the resume claims beside what the interviews showed. */
export function SkillsTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.skills");
  const score = useScore();
  if (data.skills.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <Table caption={t("caption")} columns={[t("skill"), t("resume"), t("interviews")]}>
      {data.skills.map((row) => (
        <tr key={row.skill} className="border-border border-t align-top">
          <td className="px-3 py-2 font-medium">{row.skill}</td>
          <td className="px-3 py-2">
            {row.on_resume
              ? row.resume_years
                ? t("onResumeYears", { years: row.resume_years })
                : t("onResume")
              : "—"}
          </td>
          <td className="px-3 py-2">
            {row.interviews.length === 0
              ? "—"
              : row.interviews.map((item) => `${item.reference}: ${score(item.score)}`).join(" · ")}
          </td>
        </tr>
      ))}
    </Table>
  );
}

/** Coding: what exists of the candidate's coding today; the coding service is SP-16. */
export function CodingTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.coding");
  return (
    <div className="grid max-w-3xl gap-3 text-sm">
      <p role="note" className="rounded-md border border-border bg-surface-muted px-3 py-2">
        {t("pending")}
      </p>
      {data.interviews.length === 0 ? (
        <Empty>{t("none")}</Empty>
      ) : (
        <ul className="grid gap-2">
          {data.interviews.map((item) => (
            <li key={item.interview_id} className="flex flex-wrap items-center gap-x-3">
              <span className="font-medium">{item.reference}</span>
              <span>{t("snapshots", { count: item.code_snapshots })}</span>
              <Link
                href={`/reports/coding/${item.interview_id}`}
                className="inline-flex min-h-6 items-center underline"
              >
                {t("open")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** AI interview: each interview's evaluation, with its strengths and gaps. */
export function AiInterviewTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.ai");
  if (data.interviews.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <div className="grid max-w-3xl gap-4">
      {data.interviews.map((item) => (
        <section
          key={item.interview_id}
          aria-label={item.reference}
          className="grid gap-2 rounded-lg border border-border p-4 text-sm"
        >
          <h3 className="font-semibold text-base">
            {t("heading", { reference: item.reference, job: item.job_title })}
          </h3>
          {item.evaluation.state === "none" ? (
            <p className="text-muted-foreground">{t("notEvaluated")}</p>
          ) : (
            <>
              <p>
                {t("overall")} <ScoreText value={item.evaluation.overall} />
                {" · "}
                {t("communication")} <ScoreText value={item.evaluation.communication} />
              </p>
              {item.evaluation.skills.length > 0 ? (
                <ul className="flex flex-wrap gap-x-4">
                  {item.evaluation.skills.map((skill) => (
                    <li key={skill.skill}>
                      <span className="font-medium">{skill.skill}</span>{" "}
                      <ScoreText value={skill.score} />
                    </li>
                  ))}
                </ul>
              ) : null}
              {item.evaluation.strengths.length > 0 ? (
                <div>
                  <h4 className="text-muted-foreground text-xs uppercase tracking-wide">
                    {t("strengths")}
                  </h4>
                  <ul className="list-disc pl-5">
                    {item.evaluation.strengths.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {item.evaluation.knowledge_gaps.length > 0 ? (
                <div>
                  <h4 className="text-muted-foreground text-xs uppercase tracking-wide">
                    {t("gaps")}
                  </h4>
                  <ul className="list-disc pl-5">
                    {item.evaluation.knowledge_gaps.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
          <p className="flex gap-4">
            <Link
              href={`/interviews/${item.interview_id}/review`}
              className="inline-flex min-h-6 items-center underline"
            >
              {t("review")}
            </Link>
            <Link
              href={`/reports/interview/${item.interview_id}`}
              className="inline-flex min-h-6 items-center underline"
            >
              {t("report")}
            </Link>
          </p>
        </section>
      ))}
    </div>
  );
}

/** Proctoring: how many events each interview had and how many were reviewed. Signals, not a
 * verdict. */
export function ProctoringTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.proctoring");
  const rows = data.interviews.filter((item) => item.proctoring !== null);
  if (rows.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <div className="grid gap-3">
      <p className="text-muted-foreground text-sm">{t("signals")}</p>
      <Table
        caption={t("caption")}
        columns={[t("interview"), t("critical"), t("warnings"), t("info"), t("reviewed"), ""]}
      >
        {rows.map((item) => (
          <tr key={item.interview_id} className="border-border border-t">
            <td className="px-3 py-2 font-medium">{item.reference}</td>
            <td className="px-3 py-2">{item.proctoring?.critical}</td>
            <td className="px-3 py-2">{item.proctoring?.warning}</td>
            <td className="px-3 py-2">{item.proctoring?.info}</td>
            <td className="px-3 py-2">{item.proctoring?.reviewed}</td>
            <td className="px-3 py-2">
              <Link
                href={`/reports/proctoring/${item.interview_id}`}
                className="inline-flex min-h-6 items-center underline"
              >
                {t("open")}
              </Link>
            </td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

/** Recordings: the tracks each interview has; playing them is in the review workspace, where
 * each viewing is audited. */
export function RecordingsTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.recordings");
  if (data.interviews.length === 0) return <Empty>{t("none")}</Empty>;
  return (
    <div className="grid max-w-3xl gap-4">
      <p className="text-muted-foreground text-sm">{t("audited")}</p>
      {data.interviews.map((item) => (
        <section key={item.interview_id} aria-label={item.reference} className="grid gap-2 text-sm">
          <h3 className="font-semibold">
            {item.reference}{" "}
            <Link
              href={`/interviews/${item.interview_id}/review`}
              className="font-normal underline"
            >
              {t("play")}
            </Link>
          </h3>
          {item.recordings.length === 0 ? (
            <Empty>{t("noTracks")}</Empty>
          ) : (
            <ul className="grid gap-1">
              {item.recordings.map((recording) => (
                <li key={recording.track}>
                  {t("track", {
                    label: recording.label,
                    status: recording.status.replace("-", " "),
                    length: recording.duration_ms ? clock(recording.duration_ms) : "—",
                  })}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

function reportLinks(item: InterviewHistoryItem) {
  return [
    ["interview", `/reports/interview/${item.interview_id}`],
    ["proctoring", `/reports/proctoring/${item.interview_id}`],
    ["coding", `/reports/coding/${item.interview_id}`],
  ] as const;
}

/** Reports: each interview's reports and the PDFs made of them, and the candidate's own report. */
export function ReportsTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.reports");
  const format = useFormatter();
  return (
    <div className="grid max-w-3xl gap-4 text-sm">
      <p>
        <Link href={`/reports/candidate/${data.candidate_id}`} className="font-medium underline">
          {t("candidate")}
        </Link>
      </p>
      {data.interviews.map((item) => (
        <section key={item.interview_id} aria-label={item.reference} className="grid gap-1">
          <h3 className="font-semibold">{item.reference}</h3>
          <ul className="flex flex-wrap gap-x-4">
            {reportLinks(item).map(([kind, href]) => (
              <li key={kind}>
                <Link href={href} className="inline-flex min-h-6 items-center underline">
                  {t(kind)}
                </Link>
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            {t("candidateReport", { status: t(`status.${item.candidate_report_status}`) })}
          </p>
          {item.exports.length > 0 ? (
            <ul className="grid gap-1">
              {item.exports.map((made) => (
                <li key={made.id}>
                  {t("pdf", {
                    kind: t(made.kind as "interview"),
                    when: format.dateTime(new Date(made.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                  })}{" "}
                  <a
                    href={downloadHref(made.id)}
                    className="inline-flex min-h-6 items-center underline"
                  >
                    {t("download")}
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ))}
    </div>
  );
}

/** Recruiter notes: every note on the candidate, and a form to add one. */
export function NotesTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("candidate360.notes");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const field = useId();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => addCandidateNote(data.candidate_id, body.trim()),
    onSuccess: () => {
      setBody("");
      toast.success(t("added"), {});
      void queryClient.invalidateQueries({ queryKey: reviewKeys.candidate360(data.candidate_id) });
    },
    onError: problems.show,
  });
  const references = new Map(data.interviews.map((item) => [item.interview_id, item.reference]));
  return (
    <div className="grid max-w-3xl gap-4">
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
        <div>
          <Button type="submit" size="sm" disabled={add.isPending || body.trim() === ""}>
            {t("add")}
          </Button>
        </div>
      </form>
      {data.notes.length === 0 ? (
        <Empty>{t("none")}</Empty>
      ) : (
        <ul className="grid gap-3 text-sm">
          {data.notes.map((note) => (
            <li key={note.id} className="grid gap-0.5 border-border border-t pt-2">
              <span className="text-muted-foreground text-xs">
                {t("by", {
                  name: note.author_name,
                  when: format.dateTime(new Date(note.created_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })}
                {note.interview_id && references.get(note.interview_id)
                  ? ` · ${references.get(note.interview_id)}`
                  : ""}
                {note.at_ms !== null ? ` · ${clock(note.at_ms)}` : ""}
              </span>
              <span className="whitespace-pre-wrap break-words">{note.body}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PAGE = 50;

/** The unified activity timeline (PRD §98): screening, interview, transcript, coding,
 * proctoring, recording, evaluation and recruiter actions, newest first, filterable by source. */
export function TimelineTab({ candidateId }: { candidateId: string }) {
  const t = useTranslations("candidate360.timeline");
  const sourceNames = useTranslations("candidate360.timeline.sources");
  const severities = useTranslations("interviews.proctoring.severity");
  const format = useFormatter();
  const [chosen, setChosen] = useState<Set<TimelineSource>>(new Set(TIMELINE_SOURCES));
  const all = chosen.size === TIMELINE_SOURCES.length;
  const sources = all ? undefined : TIMELINE_SOURCES.filter((source) => chosen.has(source));
  const timeline = useInfiniteQuery({
    queryKey: reviewKeys.timeline(candidateId, all ? "all" : [...chosen].sort().join(",")),
    queryFn: ({ pageParam }) =>
      getTimeline(candidateId, {
        ...(sources ? { source: [...sources] } : {}),
        ...(pageParam ? { before: pageParam } : {}),
        limit: PAGE,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
  });
  const items = timeline.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="grid max-w-4xl gap-4">
      <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <legend className="mb-1 font-medium">{t("filterBy")}</legend>
        {TIMELINE_SOURCES.map((source) => (
          <label key={source} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={chosen.has(source)}
              onChange={(event) => {
                const next = new Set(chosen);
                if (event.target.checked) next.add(source);
                else next.delete(source);
                setChosen(next.size === 0 ? new Set(TIMELINE_SOURCES) : next);
              }}
            />
            {sourceNames(source)}
          </label>
        ))}
      </fieldset>
      {timeline.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : items.length === 0 ? (
        <Empty>{t("none")}</Empty>
      ) : (
        <ol aria-label={t("title")} className="grid gap-2 text-sm">
          {items.map((item, index) => (
            <li
              // Entries have no ids; the order is the key.
              // biome-ignore lint/suspicious/noArrayIndexKey: an append-only list.
              key={index}
              className="grid gap-0.5 border-border border-t pt-2"
              data-source={item.source}
            >
              <div className="flex flex-wrap items-center gap-2">
                <time className="text-muted-foreground text-xs" dateTime={item.at}>
                  {format.dateTime(new Date(item.at), { dateStyle: "medium", timeStyle: "short" })}
                </time>
                <Badge>{sourceNames(item.source)}</Badge>
                {item.severity ? (
                  <SeverityBadge severity={item.severity} label={severities(item.severity)} />
                ) : null}
                <span className="font-medium">{item.title}</span>
                {item.interview_id && item.offset_ms !== null && item.offset_ms >= 0 ? (
                  <Link
                    href={`/interviews/${item.interview_id}/review?t=${item.offset_ms}`}
                    className="tabular-nums underline"
                    aria-label={t("jump", { title: item.title, time: clock(item.offset_ms) })}
                  >
                    {clock(item.offset_ms)}
                  </Link>
                ) : null}
                {item.actor ? (
                  <span className="text-muted-foreground text-xs">{item.actor}</span>
                ) : null}
              </div>
              {item.detail ? (
                <p className="break-words text-muted-foreground">{item.detail}</p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {timeline.hasNextPage ? (
        <div>
          <Button
            variant="secondary"
            size="sm"
            disabled={timeline.isFetchingNextPage}
            onClick={() => void timeline.fetchNextPage()}
          >
            {t("older")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** A status chip with a "Change" action that loads what the reader may do, then asks. */
export function ApplicationStatusAction({
  applicationId,
  status,
  canManage,
  onChanged,
}: {
  applicationId: string;
  status: string;
  canManage: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("hiring");
  const [asking, setAsking] = useState(false);
  const state = useQuery({
    queryKey: reviewKeys.hiring(applicationId),
    queryFn: () => getHiringState(applicationId),
    enabled: asking,
  });
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Badge>{t(`statuses.${status as "under_review"}`)}</Badge>
      {canManage ? (
        <Button size="sm" variant="ghost" onClick={() => setAsking(true)}>
          {t("change")}
        </Button>
      ) : null}
      {asking && state.data && state.data.allowed.length > 0 ? (
        <MoveDialog
          applicationId={applicationId}
          state={state.data}
          onClose={() => setAsking(false)}
          onMoved={() => {
            setAsking(false);
            onChanged();
          }}
        />
      ) : null}
    </span>
  );
}
