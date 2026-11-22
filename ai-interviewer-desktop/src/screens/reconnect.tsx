import { RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { formatRejoin, rejoinSecondsLeft } from "../interview/attempt";
import {
  type AppsToClose,
  commands,
  type InterviewSummary,
  isCommandError,
  type StartResult,
} from "../native/commands";
import { Notice, Panel, PillButton, ScreenTitle } from "../ui/kit";

/** The refusals a rejoin can meet, each with its own message. */
const REJOIN_ERRORS = [
  "resume-limit-reached",
  "interview-already-taken",
  "interview-other-device",
  "interview-in-use",
  "interview-expired",
  "media-unavailable",
  "third-eye-required",
] as const;
type RejoinError = (typeof REJOIN_ERRORS)[number] | "unknown";
/** Refusals that end the interview for good; the others (a connection still closing, the phone,
 * a busy service) let the candidate try again. */
const FINAL = [
  "resume-limit-reached",
  "interview-already-taken",
  "interview-other-device",
  "interview-expired",
] as const;

function rejoinError(failure: unknown): RejoinError {
  const code = isCommandError(failure) ? failure.code : "unknown";
  return (REJOIN_ERRORS as readonly string[]).includes(code) ? (code as RejoinError) : "unknown";
}

/**
 * One attempt (C8-9, product owner 2026-11-22): after a crash or a lost connection the
 * candidate rejoins once, within 2 minutes, from this laptop. Nothing is asked again (the
 * checks and the Terms were given at the start): only the apps the interview forbids must be
 * closed, then the interview carries on where it was, its clock never stopped.
 */
export function ReconnectScreen({
  interviewId,
  summary,
  onStarted,
  onBack,
  onError,
}: {
  interviewId: string;
  summary: InterviewSummary | undefined;
  onStarted: (start: StartResult) => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("reconnect");
  const [blocked, setBlocked] = useState<AppsToClose["blocked"]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RejoinError | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const tried = useRef(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  // A guide only: the laptop's clock may be off, so the server alone says when it's too late.
  const left = summary ? rejoinSecondsLeft(summary, now) : null;

  const rejoin = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    try {
      const briefing = await commands.briefing(interviewId);
      if (briefing.app_rules) {
        const apps = await commands.appsToClose(briefing.app_rules);
        setBlocked(apps.blocked);
        if (apps.blocked.length > 0) return; // the candidate closes them, then tries again
      }
      onStarted(await commands.start(interviewId));
    } catch (error) {
      onError(error);
      setFailure(rejoinError(error));
    } finally {
      setBusy(false);
    }
  }, [interviewId, onError, onStarted]);

  // Rejoining is what the candidate came back for: try at once.
  useEffect(() => {
    if (tried.current) return;
    tried.current = true;
    void rejoin();
  }, [rejoin]);

  const over = failure !== null && (FINAL as readonly string[]).includes(failure);
  return (
    <section className="m-auto grid w-full max-w-xl gap-6" aria-labelledby="reconnect-title">
      <Panel className="grid justify-items-center gap-5 p-10 text-center">
        <RotateCcw className="size-12 text-accent" strokeWidth={1.5} aria-hidden />
        <ScreenTitle
          id="reconnect-title"
          title={over ? t("overTitle") : t("title")}
          lead={over ? t("overBody") : t("lead", { job: summary?.job_title ?? "" })}
          className="justify-items-center"
        />
        {!over && left !== null ? (
          <p className="font-medium tabular-nums" aria-live="polite">
            {t("timeLeft", { time: formatRejoin(left) })}
          </p>
        ) : null}
        {blocked.length > 0 && !over ? (
          <Notice tone="warning" className="w-full text-left">
            <p className="font-medium">{t("closeApps")}</p>
            <ul className="mt-1 list-disc pl-5">
              {blocked.map((app) => (
                <li key={app.name}>{app.name}</li>
              ))}
            </ul>
          </Notice>
        ) : null}
        {failure ? (
          <p className="text-danger" role="alert">
            {t(`errors.${failure}`)}
          </p>
        ) : null}
        {over ? (
          <PillButton onClick={onBack}>{t("back")}</PillButton>
        ) : (
          <PillButton disabled={busy} onClick={() => void rejoin()}>
            {busy ? t("rejoining") : t("rejoin")}
          </PillButton>
        )}
      </Panel>
    </section>
  );
}
