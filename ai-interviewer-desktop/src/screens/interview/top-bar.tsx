import { cn } from "@hirevion/ui";
import { Clock3, Lock, Mic, MonitorUp, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { announcement, clockTone } from "../../interview/countdown";
import type { Health } from "../../interview/health";
import { formatClock } from "../../interview/session";
import { Wordmark } from "../../ui/emblem";

const TONES = {
  normal: "",
  low: "clock-low",
  critical: "clock-critical",
} as const;

const DOTS: Record<Health, string> = {
  starting: "bg-warning",
  ok: "bg-success",
  problem: "bg-danger",
};

export interface StatusItem {
  key: "microphone" | "screen" | "session";
  health: Health;
  /** What the item says, e.g. "Microphone: working". */
  label: string;
}

const ICONS = { microphone: Mic, screen: MonitorUp, session: Lock } as const;

/**
 * The bar across the top (C8-12, owner's reference 2026-11-24): a floating card with the mark and
 * "AI INTERVIEW", the candidate and the job, the microphone, screen and session (PRD §32), the
 * time left in its pill, and End Interview, the screen's one destructive action.
 */
export function TopBar({
  titleId,
  title,
  name,
  job,
  status,
  remaining,
  onEnd,
}: {
  titleId: string;
  /** The plain title, used when the name or job isn't known. */
  title: string;
  name?: string | undefined;
  job?: string | undefined;
  status: StatusItem[];
  remaining: number;
  onEnd: () => void;
}) {
  const t = useTranslations("interview");
  const tone = clockTone(remaining);
  // Screen readers hear the time only at five minutes and at one, never every second.
  const previous = useRef(remaining);
  const [said, setSaid] = useState("");
  useEffect(() => {
    const minutes = announcement(previous.current, remaining);
    previous.current = remaining;
    if (minutes) setSaid(t("minutesLeft", { minutes }));
  }, [remaining, t]);

  return (
    <header className="top-bar">
      <Wordmark label={t("wordmark")} className="max-md:[&>.wordmark]:sr-only" />
      <span aria-hidden className="top-bar-rule" />
      <h1 id={titleId} title={title} className="top-bar-title">
        {name && job ? (
          <>
            <span className="font-semibold">{name}</span>
            {` – ${job} – ${t("interviewWord")}`}
          </>
        ) : (
          title
        )}
      </h1>
      <ul className="top-bar-status" aria-label={t("health.title")}>
        {status.map(({ key, health, label }) => {
          const Icon = ICONS[key];
          return (
            <li key={key} title={label}>
              <Icon aria-hidden className="size-4" strokeWidth={1.75} />
              <span aria-hidden className={cn("status-dot", DOTS[health])} />
              <span className="sr-only">{label}</span>
            </li>
          );
        })}
      </ul>
      <p className={cn("clock", TONES[tone])} data-tone={tone}>
        <Clock3 aria-hidden className="size-5" strokeWidth={1.75} />
        <span className="sr-only">{t("timeLeft")} </span>
        <time>{formatClock(remaining)}</time>
      </p>
      <span className="sr-only" aria-live="polite">
        {said}
      </span>
      <button type="button" className="end-button" onClick={onEnd}>
        <Square aria-hidden className="size-3.5 fill-current" strokeWidth={0} />
        {t("end")}
      </button>
    </header>
  );
}
