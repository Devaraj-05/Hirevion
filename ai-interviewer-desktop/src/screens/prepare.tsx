import { Skeleton } from "@hirevion/ui";
import { ArrowLeft, Clock3 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "use-intl";
import type { SystemCheckPayload } from "../checks/payload";
import {
  type Briefing,
  commands,
  type InterviewSummary,
  isCommandError,
  type StartResult,
} from "../native/commands";
import { type Done, type PhoneMode, readyToStart, type StepId, steps } from "../prepare/steps";
import { Notice, Panel, PillButton } from "../ui/kit";
import { type ErrorKey, errorKey } from "./errors";
import { ChecksStep } from "./prepare/checks-step";
import { DevicesStep } from "./prepare/devices-step";
import { PhoneStep } from "./prepare/phone-step";
import { Step } from "./prepare/step";
import { TermsStep } from "./prepare/terms-step";

const START_ERRORS = [
  "third-eye-required",
  "media-unavailable",
  "checks-incomplete",
  "consents-missing",
  "interview-not-open",
  "interview-expired",
  "resume-limit-reached",
];

/**
 * Everything before the interview on one page (product owner, 2026-11-16): the company's
 * instructions beside four steps (camera and microphone, the system check, the Terms and
 * Conditions, the phone) and one Start button once they are done.
 */
export function PrepareScreen({
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
  const t = useTranslations("prepare");
  const errors = useTranslations("errors");
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loadError, setLoadError] = useState<ErrorKey | null>(null);
  const [done, setDone] = useState<Done>({
    devices: false,
    checks: false,
    terms: false,
    phone: false,
  });
  const [phoneMode, setPhoneMode] = useState<PhoneMode>("off");
  const [checkId, setCheckId] = useState("");
  const [consentId, setConsentId] = useState("");
  // A check that failed only on a required third eye waits for the phone step.
  const [recheck, setRecheck] = useState<SystemCheckPayload | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    commands
      .briefing(interviewId)
      .then((read) => {
        setBriefing(read);
        setPhoneMode(read.third_eye);
      })
      .catch((failure: unknown) => {
        onError(failure);
        setLoadError(errorKey(failure));
      });
  }, [interviewId, onError]);

  const finished = useCallback((step: StepId) => setDone((now) => ({ ...now, [step]: true })), []);

  async function start() {
    setStarting(true);
    setStartError(null);
    try {
      onStarted(await commands.start(interviewId, checkId, consentId));
    } catch (failure) {
      onError(failure);
      const code = isCommandError(failure) ? failure.code : "unknown";
      if (code === "third-eye-required") {
        // The server wants a phone the briefing didn't ask for: its step opens.
        setPhoneMode("required");
        setDone((now) => ({ ...now, phone: false }));
      }
      setStartError(START_ERRORS.includes(code) ? code : "unknown");
    } finally {
      setStarting(false);
    }
  }

  const order = steps(done, phoneMode);
  const state = (id: StepId) => order.find((step) => step.id === id)?.state ?? "locked";
  const ready = readyToStart(done, phoneMode);
  const count = order.filter((step) => step.state === "done").length;

  return (
    <div className="grid gap-8">
      <div className="grid gap-3">
        <button
          type="button"
          onClick={onBack}
          className="flex w-fit items-center gap-1.5 text-[0.9rem] text-accent hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("back")}
        </button>
        <h1 className="font-semibold text-[2rem] leading-tight">{t("title")}</h1>
        <p className="max-w-[60ch] text-muted-foreground leading-relaxed">
          {t("lead", { count: order.length })}
        </p>
      </div>

      {loadError ? (
        <Notice role="alert" tone="danger">
          {errors(loadError)}
        </Notice>
      ) : null}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17.5rem]">
        <div className="grid gap-4">
          {briefing ? (
            <>
              <Step
                number={1}
                state={state("devices")}
                title={t("devices.title")}
                lead={t("devices.lead")}
                summary={t("devices.summary")}
              >
                <DevicesStep onDone={() => finished("devices")} />
              </Step>
              <Step
                number={2}
                state={state("checks")}
                title={t("checks.title")}
                lead={t("checks.lead")}
                summary={t("checks.summary")}
              >
                <ChecksStep
                  interviewId={interviewId}
                  thirdEye={phoneMode}
                  appRules={briefing.app_rules ?? null}
                  onPassed={(id, payload, waitingForPhone) => {
                    setCheckId(id);
                    setRecheck(waitingForPhone ? payload : null);
                    finished("checks");
                  }}
                  onError={onError}
                />
              </Step>
              <Step
                number={3}
                state={state("terms")}
                title={t("terms.title")}
                lead={t("terms.lead")}
                summary={t("terms.summary")}
              >
                <TermsStep
                  interviewId={interviewId}
                  briefing={briefing}
                  onAgreed={(id) => {
                    setConsentId(id);
                    finished("terms");
                  }}
                  onError={onError}
                />
              </Step>
              {phoneMode !== "off" ? (
                <Step
                  number={4}
                  state={state("phone")}
                  title={t("phone.title")}
                  lead={
                    phoneMode === "required" ? t("phone.leadRequired") : t("phone.leadOptional")
                  }
                  summary={t("phone.summary")}
                >
                  <PhoneStep
                    interviewId={interviewId}
                    mode={phoneMode}
                    recheck={recheck}
                    onDone={(id) => {
                      if (id) {
                        setCheckId(id);
                        setRecheck(null);
                      }
                      finished("phone");
                    }}
                    onError={onError}
                  />
                </Step>
              ) : null}
            </>
          ) : loadError ? null : (
            <>
              <Skeleton className="h-28 w-full rounded-[20px]" />
              <Skeleton className="h-20 w-full rounded-[20px]" />
              <Skeleton className="h-20 w-full rounded-[20px]" />
            </>
          )}
        </div>

        <Panel className="grid gap-4 p-5 shadow-none lg:sticky lg:top-0">
          <div className="grid gap-1">
            <h2 className="font-semibold">{summary?.job_title ?? t("about")}</h2>
            {summary ? (
              <p className="flex items-center gap-1.5 text-[0.9rem] text-muted-foreground">
                <Clock3 className="size-4" aria-hidden />
                {t("minutes", { minutes: summary.duration_minutes })}
              </p>
            ) : null}
          </div>
          {briefing && briefing.instructions.length > 0 ? (
            <div className="grid gap-2 border-border/70 border-t pt-4">
              <h3 className="font-medium text-[0.9rem]">{t("instructions")}</h3>
              <ul className="grid gap-2 text-[0.88rem] text-muted-foreground leading-snug">
                {briefing.instructions.map((line) => (
                  <li key={line} className="flex gap-2">
                    <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-current" />
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>
      </div>

      <div className="chrome sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-full border border-border/70 py-2 pr-2 pl-6 shadow-[var(--shadow-md)]">
        <p role="status" aria-live="polite" className="text-[0.92rem]">
          {startError ? (
            <span className="text-danger">{t(`startErrors.${startError}`)}</span>
          ) : ready ? (
            <span className="font-medium">{t("ready")}</span>
          ) : (
            <span className="text-muted-foreground">
              {t("progress", { done: count, total: order.length })}
            </span>
          )}
        </p>
        <PillButton size="lg" disabled={!ready || starting} onClick={() => void start()}>
          {starting ? t("starting") : t("start")}
        </PillButton>
      </div>
    </div>
  );
}
