"use client";

import type { components } from "@hirevion/api-client";
import { Badge, type BadgeTone, Card, CardContent, CardHeader, CardTitle } from "@hirevion/ui";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { countdownParts, windowPhase } from "./countdown";

export type PortalInterview = components["schemas"]["PortalInterviewItem"];

// The statuses whose window still matters to the candidate.
const COUNTING = new Set(["invited", "in_progress", "interrupted"]);
// An interview that has run (or was called off) can't be moved: the API refuses it too.
const NOT_RESCHEDULABLE = new Set(["completed", "evaluating", "evaluated", "cancelled"]);
const TONES: Record<string, BadgeTone> = {
  invited: "info",
  in_progress: "warning",
  interrupted: "warning",
  completed: "success",
  evaluating: "success",
  evaluated: "success",
  expired: "neutral",
  cancelled: "neutral",
  abandoned: "neutral",
};
const STATUSES = new Set([...Object.keys(TONES), "scheduled"]);

/** The server's clock, moving: the countdown never trusts the candidate's own clock. */
function useServerNow(serverNow: string): number {
  const start = Date.parse(serverNow);
  const [now, setNow] = useState(start);
  useEffect(() => {
    const offset = start - Date.now();
    const timer = setInterval(() => setNow(Date.now() + offset), 1_000);
    return () => clearInterval(timer);
  }, [start]);
  return now;
}

function useWindowText(interview: PortalInterview): string {
  const locale = useLocale();
  const timeZone = interview.timezone;
  const format = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  });
  const opens = new Date(interview.starts_at);
  const zone =
    new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "short" })
      .formatToParts(opens)
      .find((part) => part.type === "timeZoneName")?.value ?? timeZone;
  return `${format.format(opens)} – ${format.format(new Date(interview.expires_at))} (${zone})`;
}

export function InterviewCard({
  interview,
  serverNow,
}: {
  interview: PortalInterview;
  serverNow: string;
}) {
  const t = useTranslations("portal.interviews");
  const units = useTranslations("portal.countdown");
  const now = useServerNow(serverNow);
  const window = useWindowText(interview);
  const { phase, ms } = windowPhase(
    now,
    Date.parse(interview.starts_at),
    Date.parse(interview.expires_at),
  );
  const time = countdownParts(ms)
    .map(([unit, n]) => units(unit, { n }))
    .join(" ");
  const counting = COUNTING.has(interview.status);
  const status = STATUSES.has(interview.status)
    ? t(`status.${interview.status}` as "status.invited")
    : interview.status;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-lg">{interview.job_title}</CardTitle>
        <Badge tone={TONES[interview.status] ?? "neutral"}>{status}</Badge>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
          <dt className="text-muted-foreground">{t("window")}</dt>
          <dd>{window}</dd>
          <dt className="text-muted-foreground">{t("durationLabel")}</dt>
          <dd>{t("duration", { minutes: interview.duration_minutes })}</dd>
        </dl>
        {counting ? (
          <p className="font-medium">
            {phase === "before"
              ? t("opensIn", { time })
              : phase === "open"
                ? t("closesIn", { time })
                : t("closed")}
          </p>
        ) : null}
        {counting && interview.can_take && phase === "open" ? (
          <p className="rounded-md bg-success-subtle px-3 py-2">{t("ready")}</p>
        ) : null}
        <p className="text-muted-foreground">{t("records", { what: interview.recorded })}</p>
        <div className="flex flex-wrap gap-4">
          {counting ? (
            <Link href="/download" className="font-medium text-primary underline">
              {t("getApp")}
            </Link>
          ) : null}
          {NOT_RESCHEDULABLE.has(interview.status) ? null : (
            <Link
              href={`/requests?kind=reschedule&interview=${encodeURIComponent(interview.id)}`}
              className="font-medium text-primary underline"
            >
              {t("reschedule")}
            </Link>
          )}
        </div>
        <p className="text-muted-foreground text-xs">{interview.reference}</p>
      </CardContent>
    </Card>
  );
}
