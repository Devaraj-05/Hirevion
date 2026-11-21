"use client";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  cn,
  KpiTile,
  SeverityBadge,
  Skeleton,
  TableScroll,
} from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import {
  type AnalyticsEvent,
  type AnalyticsInventory,
  type AnalyticsQuestion,
  type AnalyticsSkill,
  analyticsKeys,
  getInterviewAnalytics,
  type InterviewAnalytics,
} from "./analytics-api";
import { answerBars, splitDuration, timelinePercent, withAnswers } from "./analytics-model";
import { useEvaluationGate } from "./use-evaluation-gate";

const SCORE_MAX = 10;

/**
 * One interview's analytics (C8-7, ADR-0047; owner, 2026-11-21: "the complete analytics in the
 * recruitment dashboard for that particular candidate"): the scores per skill and per question,
 * how long each answer took, PRD §59's speech measures, and the proctoring timeline with the
 * process list at the start. The AI's numbers stay hidden until the reviewer has scored every
 * question or chosen not to (ADR-0031), like every other panel that shows them.
 */
export function InterviewAnalyticsPanel({ interviewId }: { interviewId: string }) {
  const t = useTranslations("interviews.analytics");
  const query = useQuery({
    queryKey: analyticsKeys.detail(interviewId),
    queryFn: () => getInterviewAnalytics(interviewId),
  });
  const gate = useEvaluationGate(interviewId);
  if (query.isPending) return <Skeleton className="h-96 w-full" />;
  if (query.isError) return <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>;
  const data = query.data;
  const scored = data.overall !== null;
  // Nothing about the AI's numbers until the reviewer's own scores have loaded: a reviewer who
  // has scored everything never sees the banner flash (review, 2026-11-21).
  const showScores = scored && gate.loaded && gate.revealed;
  const banner = scored && gate.loaded && !gate.revealed;
  return (
    <div className="grid gap-4">
      {banner ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface-muted p-4 text-sm">
          <p>{t("hidden", { saved: gate.progress.saved, total: gate.progress.total })}</p>
          <Button size="sm" variant="secondary" onClick={gate.waive}>
            {t("showWithoutScoring")}
          </Button>
        </div>
      ) : null}
      <Overview data={data} showScores={showScores} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <SkillsCard skills={data.skills} showScores={showScores} />
        <QuestionScoresCard
          questions={withAnswers(data.questions)}
          showScores={showScores}
          scored={scored}
          loading={scored && !gate.loaded}
        />
      </div>
      <AnswerTimingCard
        questions={withAnswers(data.questions)}
        unreliable={data.speech.pace_unreliable}
      />
      <SpeechCard speech={data.speech} />
      {data.integrity ? (
        <IntegrityCard
          integrity={data.integrity}
          durationMs={data.duration_ms}
          plannedMinutes={data.planned_minutes}
        />
      ) : null}
      <NumbersTable questions={data.questions} showScores={showScores} />
    </div>
  );
}

function useSeconds() {
  const format = useFormatter();
  return (ms: number | null) =>
    ms === null ? "—" : format.number(ms / 1000, { maximumFractionDigits: ms < 10_000 ? 1 : 0 });
}

function useScore() {
  const format = useFormatter();
  return (value: number | null) =>
    value === null ? "—" : format.number(value, { maximumFractionDigits: 1 });
}

function Overview({ data, showScores }: { data: InterviewAnalytics; showScores: boolean }) {
  const t = useTranslations("interviews.analytics.overview");
  const score = useScore();
  const seconds = useSeconds();
  const length = splitDuration(data.duration_ms);
  const answered = data.questions.filter((q) => q.status === "answered").length;
  const critical = data.integrity?.counts.CRITICAL ?? null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <KpiTile
        label={t("overall")}
        value={
          showScores && data.overall !== null ? t("outOf", { score: score(data.overall) }) : null
        }
        noDataLabel={t("noScore")}
      />
      <KpiTile
        label={t("communication")}
        value={
          showScores && data.communication !== null
            ? t("outOf", { score: score(data.communication) })
            : null
        }
        noDataLabel={t("noScore")}
      />
      <KpiTile
        label={t("length")}
        value={length ? t("minutes", { ...length }) : null}
        hint={t("planned", { minutes: data.planned_minutes })}
        noDataLabel={t("noLength")}
      />
      <KpiTile
        label={t("answered")}
        value={t("answeredOf", { answered, asked: data.questions.length })}
        noDataLabel={t("noLength")}
      />
      <KpiTile
        label={t("response")}
        value={
          data.speech.median_response_ms === null
            ? null
            : t("seconds", { seconds: seconds(data.speech.median_response_ms) })
        }
        noDataLabel={t("noSpeech")}
      />
      <KpiTile
        label={t("critical")}
        value={critical === null ? null : String(critical)}
        noDataLabel={t("noIntegrity")}
      />
    </div>
  );
}

function ChartCard({
  title,
  lead,
  children,
  className,
}: {
  title: string;
  lead?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader className="gap-1">
        <CardTitle>{title}</CardTitle>
        {lead ? <p className="text-muted-foreground text-sm">{lead}</p> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** A tooltip for a chart mark: shown on hover and on keyboard focus. */
function Tip({
  label,
  children,
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("group relative", className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-10 mb-2 w-max max-w-64 -translate-x-1/2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-left text-foreground text-xs shadow-md group-focus-within:visible group-hover:visible"
      >
        {label}
      </span>
    </span>
  );
}

function SkillsCard({ skills, showScores }: { skills: AnalyticsSkill[]; showScores: boolean }) {
  const t = useTranslations("interviews.analytics.skills");
  const score = useScore();
  return (
    <ChartCard title={t("title")} lead={t("lead")}>
      {skills.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      ) : (
        <ul className="grid gap-4">
          {skills.map((skill) => {
            const value = showScores ? skill.score : null;
            return (
              <li key={skill.skill} className="grid gap-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{skill.skill}</span>
                    {skill.required ? <Badge>{t("required")}</Badge> : null}
                    {!skill.covered ? <Badge tone="warning">{t("notCovered")}</Badge> : null}
                    {skill.dropped ? <Badge tone="neutral">{t("dropped")}</Badge> : null}
                  </span>
                  <span className="font-medium tabular-nums">
                    {value === null ? "—" : t("outOf", { score: score(value) })}
                  </span>
                </div>
                <div
                  role="img"
                  aria-label={
                    value === null
                      ? t("meterNone", { skill: skill.skill })
                      : t("meter", { skill: skill.skill, score: score(value) })
                  }
                  className="h-2 rounded-full bg-accent-subtle"
                >
                  {value !== null ? (
                    <div
                      className="h-2 rounded-full bg-chart-1"
                      style={{ width: `${Math.max(2, (value / SCORE_MAX) * 100)}%` }}
                    />
                  ) : null}
                </div>
                <p className="text-muted-foreground text-xs">
                  {t("asked", {
                    asked: skill.asked,
                    answered: skill.answered,
                    planned: skill.planned,
                  })}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </ChartCard>
  );
}

function QuestionScoresCard({
  questions,
  showScores,
  scored,
  loading,
}: {
  questions: AnalyticsQuestion[];
  showScores: boolean;
  scored: boolean;
  loading: boolean;
}) {
  const t = useTranslations("interviews.analytics.questions");
  const kinds = useTranslations("interviews.analytics.kinds");
  const score = useScore();
  const [active, setActive] = useState<string | null>(null);
  if (loading) {
    return (
      <ChartCard title={t("title")} lead={t("lead")}>
        <Skeleton className="h-44 w-full" />
      </ChartCard>
    );
  }
  if (!scored || !showScores) {
    return (
      <ChartCard title={t("title")} lead={t("lead")}>
        <p className="text-muted-foreground text-sm">{scored ? t("hidden") : t("notEvaluated")}</p>
      </ChartCard>
    );
  }
  const current = questions.find((q) => q.id === active) ?? null;
  return (
    <ChartCard title={t("title")} lead={t("lead")}>
      <div className="flex gap-3">
        <div
          className="flex h-44 flex-col justify-between pb-10 text-muted-foreground text-xs tabular-nums"
          aria-hidden
        >
          <span>{score(10)}</span>
          <span>{score(5)}</span>
          <span>{score(0)}</span>
        </div>
        <div className="relative min-w-0 flex-1 overflow-x-auto">
          <div className="relative flex h-44 min-w-fit items-end gap-1.5 pb-10">
            <div className="pointer-events-none absolute inset-x-0 top-0 border-border border-t" />
            <div className="pointer-events-none absolute inset-x-0 top-[calc((100%-2.5rem)/2)] border-border border-t" />
            <div className="pointer-events-none absolute inset-x-0 bottom-10 border-border border-t" />
            {questions.map((q) => (
              <span
                key={q.id}
                className="relative flex h-full min-w-5 max-w-7 flex-1 flex-col items-center justify-end"
              >
                <button
                  type="button"
                  aria-label={t("column", {
                    position: q.position,
                    score: q.score === null ? t("noScore") : score(q.score),
                  })}
                  aria-describedby={active === q.id ? "analytics-question-detail" : undefined}
                  onMouseEnter={() => setActive(q.id)}
                  onFocus={() => setActive(q.id)}
                  onMouseLeave={() => setActive((now) => (now === q.id ? null : now))}
                  onBlur={() => setActive((now) => (now === q.id ? null : now))}
                  className={cn(
                    "flex h-full w-full max-w-6 items-end justify-center rounded-t-[4px] outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring",
                    active !== null && active !== q.id ? "opacity-50" : "",
                  )}
                >
                  <span
                    className="w-full rounded-t-[4px] bg-chart-1"
                    style={{
                      height: `${q.score === null ? 0 : Math.max(1.5, (q.score / SCORE_MAX) * 100)}%`,
                    }}
                  />
                </button>
                <span className="absolute top-full grid h-10 place-items-center pt-1 text-center text-muted-foreground text-xs leading-tight">
                  <span>{t("number", { position: q.position })}</span>
                  <span>
                    {q.difficulty ? t(`short.${q.difficulty}` as "short.easy") : t("noLevel")}
                  </span>
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
      <div
        id="analytics-question-detail"
        role="status"
        aria-label={t("detailLabel")}
        className="mt-3 min-h-14 rounded-md bg-surface-muted px-3 py-2 text-sm"
      >
        {current ? (
          <>
            <span className="block font-medium">
              {t("tipTitle", { position: current.position, kind: kinds(current.kind as "main") })}
              {" · "}
              {current.score === null ? t("noScore") : t("outOf", { score: score(current.score) })}
            </span>
            <span className="block text-muted-foreground">{current.text}</span>
          </>
        ) : (
          <span className="text-muted-foreground">{t("detailHint")}</span>
        )}
      </div>
      <p className="mt-2 text-muted-foreground text-xs">{t("legend")}</p>
    </ChartCard>
  );
}

function AnswerTimingCard({
  questions,
  unreliable,
}: {
  questions: AnalyticsQuestion[];
  /** The stored speech times are too short (answers recorded before the agent's fix). */
  unreliable: boolean;
}) {
  const t = useTranslations("interviews.analytics.timing");
  const seconds = useSeconds();
  const bars = answerBars(questions);
  const byPosition = new Map(questions.map((q) => [q.position, q]));
  return (
    <ChartCard title={t("title")} lead={t("lead")}>
      {unreliable ? (
        <p className="mb-3 rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning">
          {t("unreliable")}
        </p>
      ) : null}
      {questions.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      ) : (
        <div className="grid gap-3">
          <ul className="flex flex-wrap gap-4 text-sm" aria-label={t("legendLabel")}>
            <li className="flex items-center gap-2">
              <span className="size-3 rounded-sm bg-chart-2" aria-hidden />
              {t("thinking")}
            </li>
            <li className="flex items-center gap-2">
              <span className="size-3 rounded-sm bg-chart-1" aria-hidden />
              {t("speaking")}
            </li>
          </ul>
          <ol className="grid gap-2">
            {bars.rows.map((row) => {
              const q = byPosition.get(row.position);
              const label = t("row", {
                position: row.position,
                skill: q?.skill ?? t("general"),
              });
              const detail = t("tip", {
                thinking: seconds(row.thinkingMs),
                speaking: seconds(row.speakingMs),
              });
              return (
                <li
                  key={row.position}
                  className="grid grid-cols-[7.5rem_1fr] items-center gap-3 text-sm"
                >
                  <span className="truncate text-muted-foreground" title={label}>
                    {label}
                  </span>
                  <Tip
                    label={
                      <>
                        <span className="block font-medium">{label}</span>
                        <span className="block text-muted-foreground">{q?.text}</span>
                        <span className="block">{detail}</span>
                      </>
                    }
                    className="flex min-w-0 items-center gap-2"
                  >
                    <button
                      type="button"
                      aria-label={`${label}: ${detail}`}
                      className="flex h-5 min-w-0 flex-1 items-center gap-0.5 rounded-sm outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      {row.thinking > 0 ? (
                        <span
                          className={cn(
                            "h-3.5 bg-chart-2",
                            row.speaking > 0 ? "" : "rounded-r-[4px]",
                          )}
                          style={{ width: `${row.thinking}%` }}
                        />
                      ) : null}
                      {row.speaking > 0 ? (
                        <span
                          className="h-3.5 rounded-r-[4px] bg-chart-1"
                          style={{ width: `${row.speaking}%` }}
                        />
                      ) : null}
                      <span className="ml-1 shrink-0 text-muted-foreground text-xs tabular-nums">
                        {t("total", { seconds: seconds((row.thinkingMs ?? 0) + row.speakingMs) })}
                      </span>
                    </button>
                  </Tip>
                </li>
              );
            })}
          </ol>
          <div
            className="grid grid-cols-[7.5rem_1fr] gap-3 text-muted-foreground text-xs tabular-nums"
            aria-hidden
          >
            <span />
            <span className="flex justify-between border-border border-t pt-1">
              <span>{seconds(0)}</span>
              <span>{t("seconds", { seconds: seconds(bars.max / 2) })}</span>
              <span>{t("seconds", { seconds: seconds(bars.max) })}</span>
            </span>
          </div>
        </div>
      )}
    </ChartCard>
  );
}

function SpeechCard({ speech }: { speech: InterviewAnalytics["speech"] }) {
  const t = useTranslations("interviews.analytics.speech");
  const format = useFormatter();
  const candidate = splitDuration(speech.candidate_ms);
  const interviewer = splitDuration(speech.ai_ms);
  const share = speech.candidate_share;
  const fillers = Object.entries(speech.fillers).sort((a, b) => b[1] - a[1]);
  const stats: [string, string][] = [
    [t("words"), format.number(speech.words)],
    [
      t("pace"),
      speech.words_per_minute !== null
        ? t("wpm", { wpm: speech.words_per_minute })
        : speech.pace_unreliable
          ? t("paceUnreliable")
          : "—",
    ],
    [
      t("medianWait"),
      speech.median_response_ms === null
        ? "—"
        : t("seconds", {
            seconds: format.number(speech.median_response_ms / 1000, { maximumFractionDigits: 1 }),
          }),
    ],
    [t("longPauses"), format.number(speech.long_pauses)],
    [
      t("fillers"),
      speech.fillers_per_100_words === null
        ? "—"
        : t("fillersRate", {
            rate: format.number(speech.fillers_per_100_words, { maximumFractionDigits: 1 }),
          }),
    ],
  ];
  return (
    <ChartCard title={t("title")} lead={t("lead")}>
      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <div className="grid content-start gap-3">
          <p className="font-medium text-sm">{t("talkTitle")}</p>
          {share === null ? (
            <p className="text-muted-foreground text-sm">{t("noSpeech")}</p>
          ) : (
            <>
              <div
                role="img"
                aria-label={t("talkLabel", { share: Math.round(share * 100) })}
                className="flex h-2 gap-0.5"
              >
                <span className="rounded-l-full bg-chart-1" style={{ width: `${share * 100}%` }} />
                <span className="flex-1 rounded-r-full bg-border" />
              </div>
              <ul className="grid gap-1.5 text-sm">
                <li className="flex items-center gap-2">
                  <span className="size-3 rounded-sm bg-chart-1" aria-hidden />
                  <span className="flex-1">{t("candidate")}</span>
                  <span className="tabular-nums">
                    {t("spoke", {
                      time: candidate ? t("duration", { ...candidate }) : "—",
                      share: Math.round(share * 100),
                    })}
                  </span>
                </li>
                <li className="flex items-center gap-2">
                  <span className="size-3 rounded-sm bg-border" aria-hidden />
                  <span className="flex-1">{t("interviewer")}</span>
                  <span className="tabular-nums">
                    {t("spoke", {
                      time: interviewer ? t("duration", { ...interviewer }) : "—",
                      share: Math.round((1 - share) * 100),
                    })}
                  </span>
                </li>
              </ul>
            </>
          )}
        </div>
        <div className="grid content-start gap-3">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {stats.map(([label, value]) => (
              <div key={label} className="grid gap-0.5 rounded-lg bg-surface-muted p-3">
                <dt className="text-muted-foreground text-xs">{label}</dt>
                <dd className="font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
          {fillers.length > 0 ? (
            <p className="text-sm">
              {t("fillersFound", {
                list: fillers.map(([word, count]) => `“${word}” ×${count}`).join(", "),
              })}
            </p>
          ) : null}
          {speech.pace_unreliable ? (
            <p className="text-muted-foreground text-xs">{t("paceNote")}</p>
          ) : null}
        </div>
      </div>
      <p className="mt-4 border-border border-t pt-3 text-muted-foreground text-xs">
        {t("caveat")}
      </p>
    </ChartCard>
  );
}

const SEVERITY_DOT: Record<AnalyticsEvent["severity"], string> = {
  CRITICAL: "bg-danger",
  WARNING: "bg-warning",
  INFO: "bg-info",
};

function IntegrityCard({
  integrity,
  durationMs: ended,
  plannedMinutes,
}: {
  integrity: NonNullable<InterviewAnalytics["integrity"]>;
  durationMs: number | null;
  plannedMinutes: number;
}) {
  // An interview without an end yet (interrupted, still running): its planned length, or the
  // last event if that came later.
  const durationMs =
    ended ??
    Math.max(plannedMinutes * 60_000, ...integrity.events.map((event) => event.offset_ms ?? 0));
  const t = useTranslations("interviews.analytics.integrity");
  const labels = useTranslations("interviews.proctoring.events");
  const length = splitDuration(durationMs);
  const shown = integrity.events.filter((e) => e.event !== "PROCESS_INVENTORY");
  const grouped = new Map<string, { count: number; severity: AnalyticsEvent["severity"] }>();
  for (const event of shown) {
    const item = grouped.get(event.event) ?? { count: 0, severity: event.severity };
    item.count += 1;
    grouped.set(event.event, item);
  }
  const label = (event: string) =>
    labels.has(event as "FACE_ABSENT") ? labels(event as "FACE_ABSENT") : event;
  return (
    <ChartCard title={t("title")} lead={t("lead")}>
      <div className="grid gap-5">
        <ul className="flex flex-wrap gap-2" aria-label={t("countsLabel")}>
          {(["CRITICAL", "WARNING", "INFO"] as const).map((severity) => (
            <li key={severity} className="flex items-center gap-2 text-sm">
              <SeverityBadge severity={severity} label={t(`severity.${severity}`)} />
              <span className="tabular-nums">{integrity.counts[severity] ?? 0}</span>
            </li>
          ))}
        </ul>
        {shown.length > 0 ? (
          <div className="grid gap-1">
            <p className="font-medium text-sm">{t("timeline")}</p>
            <div className="relative h-10">
              <div className="absolute inset-x-0 top-1/2 border-border border-t" />
              {shown.map((event) => {
                const left = timelinePercent(event.offset_ms, durationMs);
                if (left === null) return null;
                const at = splitDuration(event.offset_ms);
                const review = event.review
                  ? ` · ${t(`review.${event.review}` as "review.confirmed")}`
                  : "";
                const text = `${label(event.event)} · ${at ? t("at", { ...at }) : "—"}${review}`;
                const dismissed =
                  event.review === "false_positive" || event.review === "not_relevant";
                return (
                  <span
                    key={event.id}
                    className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                    style={{ left: `${left}%` }}
                  >
                    <Tip label={text}>
                      <button
                        type="button"
                        aria-label={text}
                        className={cn(
                          "block size-3 rounded-full ring-2 ring-surface outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring",
                          SEVERITY_DOT[event.severity],
                          dismissed ? "opacity-40" : "",
                        )}
                      />
                    </Tip>
                  </span>
                );
              })}
            </div>
            <div className="flex justify-between text-muted-foreground text-xs tabular-nums">
              <span>{t("start")}</span>
              <span>{length ? t("at", { ...length }) : ""}</span>
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("none")}</p>
        )}
        {grouped.size > 0 ? (
          <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
            {[...grouped.entries()].map(([event, item]) => (
              <li key={event} className="flex items-center gap-2">
                <span
                  className={cn("size-2.5 shrink-0 rounded-full", SEVERITY_DOT[item.severity])}
                  aria-hidden
                />
                <span className="flex-1">{label(event)}</span>
                <span className="tabular-nums">{t("times", { count: item.count })}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <Inventory inventory={integrity.inventory} />
      </div>
    </ChartCard>
  );
}

function Inventory({ inventory }: { inventory: AnalyticsInventory | null }) {
  const t = useTranslations("interviews.analytics.inventory");
  if (!inventory) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  return (
    <div className="grid gap-2 border-border border-t pt-4">
      <p className="font-medium text-sm">
        {t("title", { count: inventory.count ?? inventory.processes.length })}
      </p>
      {inventory.windows.length > 0 ? (
        <p className="text-sm">
          <span className="text-muted-foreground">{t("windows")} </span>
          {[...new Set(inventory.windows)].join(", ")}
        </p>
      ) : null}
      <details className="text-sm">
        <summary className="cursor-pointer text-accent hover:underline">{t("showAll")}</summary>
        <TableScroll
          label={t("tableLabel")}
          className="mt-2 max-h-80 rounded-lg border border-border"
        >
          <table className="w-full text-left text-xs">
            <caption className="sr-only">{t("tableLabel")}</caption>
            <thead className="sticky top-0 bg-surface-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("name")}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("publisher")}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("window")}
                </th>
              </tr>
            </thead>
            <tbody>
              {programs(inventory).map((program) => (
                <tr key={program.key} className="border-border border-t align-top">
                  <td className="px-3 py-1.5 font-medium">
                    {program.count > 1
                      ? t("program", { name: program.name, count: program.count })
                      : program.name}
                  </td>
                  <td className="px-3 py-1.5">{program.publisher ?? "—"}</td>
                  <td className="break-words px-3 py-1.5">{program.window ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </details>
    </div>
  );
}

/** The process list, one row per program: its processes counted, its first window shown. */
function programs(inventory: AnalyticsInventory) {
  const rows = new Map<
    string,
    { key: string; name: string; publisher: string | null; window: string | null; count: number }
  >();
  for (const process of inventory.processes) {
    const key = `${process.name}|${process.path ?? ""}`;
    const row = rows.get(key) ?? {
      key,
      name: process.name,
      publisher: process.publisher ?? null,
      window: null,
      count: 0,
    };
    row.count += 1;
    row.window = row.window ?? process.window_titles?.[0] ?? null;
    rows.set(key, row);
  }
  return [...rows.values()].sort((a, b) => Number(b.window !== null) - Number(a.window !== null));
}

/** The charts' numbers as a table (an accessible view of every chart above). */
function NumbersTable({
  questions,
  showScores,
}: {
  questions: AnalyticsQuestion[];
  showScores: boolean;
}) {
  const t = useTranslations("interviews.analytics.table");
  const kinds = useTranslations("interviews.analytics.kinds");
  const quality = useTranslations("interviews.analytics.quality");
  const levels = useTranslations("interviews.analytics.questions");
  const seconds = useSeconds();
  const score = useScore();
  return (
    <details className="rounded-lg border border-border p-4 text-sm">
      <summary className="cursor-pointer font-medium">{t("show")}</summary>
      <TableScroll label={t("caption")} className="mt-3">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("caption")}</caption>
          <thead className="bg-surface-muted">
            <tr>
              {[
                t("question"),
                t("kind"),
                t("skill"),
                t("difficulty"),
                t("score"),
                t("thinking"),
                t("speaking"),
                t("words"),
                t("quality"),
              ].map((column) => (
                <th key={column} scope="col" className="px-3 py-2 font-medium">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {questions.map((q) => (
              <tr key={q.id} className="border-border border-t align-top">
                <td className="max-w-80 px-3 py-2">
                  <span className="font-medium">{t("number", { position: q.position })}</span>{" "}
                  <span className="text-muted-foreground">{q.text}</span>
                </td>
                <td className="px-3 py-2">{kinds(q.kind as "main")}</td>
                <td className="px-3 py-2">{q.skill ?? "—"}</td>
                <td className="px-3 py-2">
                  {q.difficulty ? levels(`difficulty.${q.difficulty}` as "difficulty.easy") : "—"}
                </td>
                <td className="px-3 py-2 tabular-nums">{showScores ? score(q.score) : "—"}</td>
                <td className="px-3 py-2 tabular-nums">{seconds(q.thinking_ms)}</td>
                <td className="px-3 py-2 tabular-nums">{seconds(q.speaking_ms)}</td>
                <td className="px-3 py-2 tabular-nums">{q.words}</td>
                <td className="px-3 py-2">{q.quality ? quality(q.quality as "strong") : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </details>
  );
}
