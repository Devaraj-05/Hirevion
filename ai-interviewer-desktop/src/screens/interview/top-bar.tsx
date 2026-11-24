import { cn } from "@hirevion/ui";
import { PhoneOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { announcement, clockTone } from "../../interview/countdown";
import { formatClock } from "../../interview/session";
import { Wordmark } from "../../ui/emblem";

const TONES = {
  normal: "text-foreground",
  low: "text-warning",
  critical: "text-danger",
} as const;

/**
 * The bar across the top (C8-12): the mark, who and what this interview is, the time left, and
 * End interview, the screen's one destructive action. It floats as a translucent material.
 */
export function TopBar({
  titleId,
  title,
  remaining,
  onEnd,
}: {
  titleId: string;
  title: string;
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
    <header className="chrome top-bar z-20 flex h-14 items-center gap-4 px-5">
      <Wordmark label={t("wordmark")} className="max-md:[&>.wordmark]:sr-only" />
      <span aria-hidden className="h-5 w-px shrink-0 bg-border" />
      <h1
        id={titleId}
        title={title}
        className="min-w-0 flex-1 truncate font-medium text-[0.95rem] tracking-[-0.01em]"
      >
        {title}
      </h1>
      <p className={cn("clock flex items-baseline gap-1.5", TONES[tone])} data-tone={tone}>
        <span className="sr-only">{t("timeLeft")} </span>
        <time className="font-semibold text-[1.15rem] tabular-nums tracking-[-0.01em]">
          {formatClock(remaining)}
        </time>
        <span aria-hidden className="text-[0.8rem] text-muted-foreground">
          {t("left")}
        </span>
      </p>
      <span className="sr-only" aria-live="polite">
        {said}
      </span>
      <button type="button" className="end-button" onClick={onEnd}>
        <PhoneOff aria-hidden className="size-4" strokeWidth={2} />
        {t("end")}
      </button>
    </header>
  );
}
