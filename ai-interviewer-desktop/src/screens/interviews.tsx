import { CalendarClock, Clock3, Code2, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "use-intl";
import { formatRejoin, listed, offerFor, rejoinSecondsLeft } from "../interview/attempt";
import { commands, type InterviewSummary, type Profile } from "../native/commands";
import { Panel, PillButton } from "../ui/kit";

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
  onRejoin,
  onProfile,
}: {
  profile: Profile;
  onStart: (interviewId: string) => void;
  onRejoin: (interviewId: string) => void;
  onProfile: (profile: Profile) => void;
}) {
  const t = useTranslations("interviews");
  const format = useFormatter();
  const now = useNow(1000);
  // The list is the server's every time it shows (C8-9): a submitted interview drops out of it.
  useEffect(() => {
    let live = true;
    commands
      .profile()
      .then((fresh) => {
        if (live) onProfile(fresh);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [onProfile]);
  const open = profile.interviews.filter((interview) => listed(interview, now));
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  return (
    <section className="grid gap-8" aria-labelledby="interviews-title">
      <div className="grid gap-2">
        <p className="text-muted-foreground">{t("hello", { name: profile.candidate.name })}</p>
        <h1 id="interviews-title" className="font-semibold text-[2rem] leading-tight">
          {t("title")}
        </h1>
      </div>
      {open.length === 0 ? (
        <Panel className="grid justify-items-center gap-3 p-12 text-center shadow-none">
          <CalendarClock className="size-10 text-muted-foreground" strokeWidth={1.5} aria-hidden />
          <p className="text-muted-foreground">{t("empty")}</p>
        </Panel>
      ) : (
        <ul className="grid gap-4">
          {open.map((interview) => {
            const window = windowState(interview, now);
            return (
              <li key={interview.id}>
                <Panel className="grid gap-5 p-6 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                  <div className="grid gap-3">
                    <div className="grid gap-1">
                      <h2 className="font-semibold text-[1.2rem]">{interview.job_title}</h2>
                      <p className="text-muted-foreground">{profile.organization.name}</p>
                    </div>
                    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-[0.9rem] text-muted-foreground">
                      <li className="flex items-center gap-1.5">
                        <Clock3 className="size-4" aria-hidden />
                        {t("duration", { minutes: interview.duration_minutes })}
                      </li>
                      {interview.coding ? (
                        <li className="flex items-center gap-1.5">
                          <Code2 className="size-4" aria-hidden />
                          {t("coding")}
                        </li>
                      ) : null}
                      {interview.third_eye !== "off" ? (
                        <li className="flex items-center gap-1.5">
                          <Smartphone className="size-4" aria-hidden />
                          {interview.third_eye === "required"
                            ? t("thirdEyeRequired")
                            : t("thirdEyeOptional")}
                        </li>
                      ) : null}
                    </ul>
                    <p className="text-[0.9rem] text-muted-foreground">
                      {window.open
                        ? t("closes", { date: when(interview.expires_at) })
                        : t("opens", { date: when(interview.starts_at) })}
                    </p>
                  </div>
                  <InterviewAction
                    interview={interview}
                    now={now}
                    msUntilOpen={window.msUntilOpen}
                    onStart={onStart}
                    onRejoin={onRejoin}
                  />
                </Panel>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The card's action, from what the server allows (one attempt, C8-9). */
function InterviewAction({
  interview,
  now,
  msUntilOpen,
  onStart,
  onRejoin,
}: {
  interview: InterviewSummary;
  now: number;
  msUntilOpen: number;
  onStart: (interviewId: string) => void;
  onRejoin: (interviewId: string) => void;
}) {
  const t = useTranslations("interviews");
  const offer = offerFor(interview, now);
  if (offer === "start") {
    return (
      <PillButton size="lg" onClick={() => onStart(interview.id)}>
        {t("start")}
      </PillButton>
    );
  }
  if (offer === "rejoin") {
    const left = rejoinSecondsLeft(interview, now);
    return (
      <div className="grid justify-items-end gap-1.5">
        <PillButton size="lg" onClick={() => onRejoin(interview.id)}>
          {t("rejoin")}
        </PillButton>
        {left !== null ? (
          <p className="text-[0.9rem] text-muted-foreground tabular-nums" aria-live="polite">
            {t("rejoinWithin", { time: formatRejoin(left) })}
          </p>
        ) : null}
      </div>
    );
  }
  if (offer === "elsewhere") {
    return <p className="font-medium text-muted-foreground">{t("elsewhere")}</p>;
  }
  return (
    <p className="font-medium tabular-nums" aria-live="polite">
      {t("startsIn", { time: formatCountdown(msUntilOpen) })}
    </p>
  );
}
