import { cn } from "@hirevion/ui";
import { LogOut, Mic, MonitorUp, Smartphone, Video } from "lucide-react";
import { type ReactNode, useId } from "react";
import { useTranslations } from "use-intl";
import type { Health, Indicators } from "../interview/health";
import { formatClock } from "../interview/session";
import type { VoiceState } from "../native/commands";
import { PillButton, StatusPill } from "../ui/kit";

export type Connection = "connecting" | "connected" | "reconnecting" | "off";

const CONNECTION_TONES = {
  connecting: "warning",
  connected: "success",
  reconnecting: "warning",
  off: "neutral",
} as const;

const PARTS = [
  { key: "camera", icon: Video },
  { key: "microphone", icon: Mic },
  { key: "screen", icon: MonitorUp },
  { key: "phone", icon: Smartphone },
] as const;

const DOTS: Record<Health, string> = {
  starting: "bg-warning",
  ok: "bg-success",
  problem: "bg-danger",
};

/** The clock turns red for the last two minutes. */
const LOW_SECONDS = 120;

/**
 * What the candidate sees during the interview (product owner, 2026-11-16): the window's
 * whole height, a bar with the time left and Exit at the top right, the interviewer as a
 * soft sphere, and, while it speaks, its words (at most 250 characters, moving up as it goes
 * on). Nothing else to press: the candidate just talks. `side` holds a coding or design
 * question's workspace, or typed answers where speech can't be used.
 */
export function InterviewStage({
  connection,
  indicators,
  remaining,
  voice,
  caption,
  side,
  notices,
  onExit,
}: {
  connection: Connection;
  indicators: Indicators;
  remaining: number;
  voice: VoiceState;
  caption: string;
  side: ReactNode | null;
  notices: ReactNode;
  onExit: () => void;
}) {
  const t = useTranslations("interview");
  const id = useId();
  const split = side !== null;
  const speaking = voice === "speaking" && connection !== "off";

  return (
    <div className="relative grid h-full grid-rows-[auto_minmax(0,1fr)]">
      <header className="chrome z-10 grid h-14 grid-cols-[1fr_auto_1fr] items-center gap-4 border-border/70 border-b px-6">
        <div className="flex min-w-0 items-center gap-2">
          <h1 id={`${id}-title`} className="mr-1 font-semibold tracking-tight max-lg:sr-only">
            {t("title")}
          </h1>
          <StatusPill tone={CONNECTION_TONES[connection]}>
            {t(`connection.${connection}`)}
          </StatusPill>
        </div>
        <p
          className={`font-medium text-[1.05rem] tabular-nums ${remaining <= LOW_SECONDS ? "text-danger" : "text-foreground"}`}
        >
          <span className="sr-only">{t("timeLeft")} </span>
          <time>{formatClock(remaining)}</time>
        </p>
        <div className="flex items-center justify-end gap-4">
          <ul className="flex items-center gap-3" aria-label={t("health.title")}>
            {PARTS.map(({ key, icon: Icon }) => {
              const health = indicators[key];
              if (health === null) return null;
              const label = `${t(`health.${key}`)}: ${t(`health.${health}`)}`;
              return (
                <li key={key} title={label} className="relative text-muted-foreground">
                  <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
                  <span
                    aria-hidden
                    className={cn(
                      "absolute -right-0.5 -bottom-0.5 size-2 rounded-full ring-2 ring-background",
                      DOTS[health],
                    )}
                  />
                  <span className="sr-only">{label}</span>
                </li>
              );
            })}
          </ul>
          <PillButton variant="secondary" className="h-9 px-4 text-danger" onClick={onExit}>
            <LogOut aria-hidden />
            {t("exit")}
          </PillButton>
        </div>
      </header>

      <main
        aria-labelledby={`${id}-title`}
        className={
          split ? "grid min-h-0 grid-cols-[minmax(17rem,0.75fr)_minmax(0,1.5fr)]" : "grid min-h-0"
        }
      >
        <section
          className="grid min-h-0 place-content-center justify-items-center gap-6 overflow-hidden px-8 py-6 text-center"
          aria-live="polite"
        >
          <div
            className={`orb ${split ? "size-28" : "size-40"}`}
            data-voice={connection === "off" ? "paused" : voice}
            aria-hidden
          />
          <p className="font-medium text-muted-foreground">
            {connection === "off" ? t("voiceOff") : t(`voice.${voice}`)}
          </p>
          {/* A fixed height, so the interviewer doesn't jump as its words come and go. */}
          <div className={`h-32 w-full ${split ? "max-w-sm" : "max-w-2xl"}`}>
            {speaking && caption ? (
              <p
                className={`caption text-balance leading-relaxed ${split ? "text-base" : "text-[1.3rem]"}`}
              >
                {caption}
              </p>
            ) : null}
          </div>
        </section>

        {split ? (
          <section className="min-h-0 overflow-y-auto border-border/70 border-l bg-surface px-8 py-6">
            <div className="mx-auto grid max-w-3xl gap-5">{side}</div>
          </section>
        ) : null}
      </main>

      {/* What needs the candidate's attention, said once, out of the way. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-6 z-10 grid justify-items-center gap-2 px-6 [&>*]:pointer-events-auto [&>*]:max-w-xl">
        {notices}
      </div>
    </div>
  );
}
