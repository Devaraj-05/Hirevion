import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@hirevion/ui";
import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "use-intl";
import type { InterviewSummary, Profile } from "../native/commands";

/** Whether an interview can be started now, and how long until it opens. */
export function windowState(interview: InterviewSummary, nowMs: number) {
  const opens = Date.parse(interview.starts_at);
  const closes = Date.parse(interview.expires_at);
  if (nowMs >= closes) return { open: false, closed: true, msUntilOpen: 0 } as const;
  return { open: nowMs >= opens, closed: false, msUntilOpen: Math.max(0, opens - nowMs) } as const;
}

/** "2 h 05 min", "4 min 10 s": the countdown on a window that hasn't opened. */
export function formatCountdown(ms: number): string {
  const seconds = Math.ceil(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, "0")} min`;
  return `${minutes} min ${String(rest).padStart(2, "0")} s`;
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** The candidate's interviews with their windows (PRD §26 "Load Interview"). */
export function InterviewsScreen({
  profile,
  onStart,
}: {
  profile: Profile;
  onStart: (interviewId: string) => void;
}) {
  const t = useTranslations("interviews");
  const format = useFormatter();
  const now = useNow(1000);
  const open = profile.interviews.filter((interview) => !windowState(interview, now).closed);

  return (
    <section className="grid gap-4" aria-labelledby="interviews-title">
      <div className="grid gap-1">
        <h1 id="interviews-title" className="font-semibold text-2xl">
          {t("title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {t("hello", { name: profile.candidate.name })}
        </p>
      </div>
      {open.length === 0 ? <p className="text-muted-foreground">{t("empty")}</p> : null}
      {open.map((interview) => {
        const window = windowState(interview, now);
        return (
          <Card key={interview.id}>
            <CardHeader>
              <CardTitle>
                {t("job", { job: interview.job_title, company: profile.organization.name })}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge>{t("duration", { minutes: interview.duration_minutes })}</Badge>
                {interview.coding ? <Badge tone="info">{t("coding")}</Badge> : null}
                {interview.third_eye === "required" ? (
                  <Badge tone="warning">{t("thirdEyeRequired")}</Badge>
                ) : interview.third_eye === "optional" ? (
                  <Badge>{t("thirdEyeOptional")}</Badge>
                ) : null}
              </div>
              <p className="text-muted-foreground">
                {window.open
                  ? t("closes", {
                      date: format.dateTime(new Date(interview.expires_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })
                  : t("opens", {
                      date: format.dateTime(new Date(interview.starts_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    })}
              </p>
              {window.open ? (
                <Button className="w-fit" onClick={() => onStart(interview.id)}>
                  {t("start")}
                </Button>
              ) : (
                <p className="font-medium" aria-live="polite">
                  {t("startsIn", { time: formatCountdown(window.msUntilOpen) })}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}
