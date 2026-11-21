import { Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { checkCamera } from "../../checks/camera";
import { checkMicrophone } from "../../checks/microphone";
import { networkResult } from "../../checks/network";
import type { SystemCheckPayload } from "../../checks/payload";
import { buildPayload, missingMandatory } from "../../checks/payload";
import { playTestTone, speakerResult } from "../../checks/speaker";
import { webview2Result } from "../../checks/thresholds";
import type { CheckResult } from "../../checks/types";
import { commands } from "../../native/commands";
import { onlyThirdEyeFailed, type ThirdEyeMode } from "../../third-eye/pairing";
import { Notice, PillButton } from "../../ui/kit";
import { type ErrorKey, errorKey } from "../errors";
import { ResultLine, showAboveBar } from "./step";

type Phase = "running" | "speaker" | "submitting" | "failed" | "error";

async function nativeResults(): Promise<CheckResult[]> {
  const [native, capture] = await Promise.all([
    commands.nativeChecks(),
    commands.screenCaptureProbe(),
  ]);
  return [...native, capture];
}

async function network(): Promise<CheckResult> {
  try {
    return networkResult((await commands.apiRoundTrip()).rtt_ms);
  } catch {
    return networkResult(null);
  }
}

/**
 * Step 2, PRD §29: the native checks run in Rust while the webview checks the camera, the
 * microphone (the candidate says a few words) and the network; the candidate confirms the
 * test sound; the API decides from the interview's policy whether the computer passes.
 */
export function ChecksStep({
  interviewId,
  thirdEye,
  onPassed,
  onError,
}: {
  interviewId: string;
  thirdEye: ThirdEyeMode;
  /** `waitingForPhone`: it failed only on a required third eye, which the phone step sets up
   * and then sends this check again. */
  onPassed: (systemCheckId: string, payload: SystemCheckPayload, waitingForPhone: boolean) => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("checks");
  const p = useTranslations("prepare.checks");
  const errors = useTranslations("errors");
  const [phase, setPhase] = useState<Phase>("running");
  const [results, setResults] = useState<CheckResult[]>([]);
  const [listening, setListening] = useState(false);
  const [failed, setFailed] = useState<string[]>([]);
  const [error, setError] = useState<ErrorKey | null>(null);
  const appVersion = useRef("unknown");
  const started = useRef(false);
  const question = useRef<HTMLDivElement>(null);
  // The sound question appears under the results: bring it into view.
  useEffect(() => {
    if (phase === "speaker") showAboveBar(question.current);
  }, [phase]);

  async function run() {
    try {
      await measure();
    } catch (failure) {
      setListening(false);
      onError(failure);
      setError(errorKey(failure));
      setPhase("error");
    }
  }

  async function measure() {
    setPhase("running");
    setError(null);
    setFailed([]);
    setResults([]);
    const info = await commands.appInfo().catch(() => null);
    appVersion.current = info?.version ?? "unknown";
    const native = nativeResults();
    const web: CheckResult[] = [webview2Result(navigator.userAgent), await network()];
    setResults([...web]);
    web.push(await checkCamera());
    setResults([...web]);
    setListening(true);
    web.push(await checkMicrophone());
    setListening(false);
    const all = [...(await native), ...web];
    setResults(all);
    setPhase("speaker");
  }

  // The check starts by itself when the step opens (development's double mount runs it once).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void run();
  });

  async function finish(heardTone: boolean) {
    const all = [...results, speakerResult(heardTone)];
    setResults(all);
    setPhase("submitting");
    const payload = buildPayload({ appVersion: appVersion.current, native: all, web: [] });
    try {
      const submitted = await commands.submitChecks(interviewId, payload);
      if (submitted.passed) {
        onPassed(submitted.id, payload, false);
        return;
      }
      if (thirdEye === "required" && onlyThirdEyeFailed(submitted.failed_mandatory)) {
        onPassed(submitted.id, payload, true);
        return;
      }
      setFailed(submitted.failed_mandatory);
      setPhase("failed");
    } catch (failure) {
      onError(failure);
      setFailed(missingMandatory(payload.results));
      setError(errorKey(failure));
      setPhase("error");
    }
  }

  const shown = buildPayload({ appVersion: "", native: results, web: [] }).results.filter(
    (result) => result.check !== "third_eye" && result.status !== "skipped",
  );
  return (
    <div className="grid gap-5">
      {shown.length > 0 ? (
        <ul className="grid gap-x-8 sm:grid-cols-2" aria-label={t("title")}>
          {shown.map((result) => (
            <ResultLine
              key={result.check}
              tone={result.status === "skipped" ? "pending" : result.status}
              label={t(`names.${result.check}` as "names.camera")}
              detail={result.status === "pass" ? null : (result.detail ?? result.value ?? null)}
            />
          ))}
        </ul>
      ) : null}

      {phase === "running" ? (
        <p role="status" className="text-[0.92rem] text-muted-foreground">
          {listening ? p("speak") : p("running")}
        </p>
      ) : null}

      {phase === "speaker" ? (
        <div ref={question} className="grid scroll-mb-28 gap-3 rounded-2xl bg-surface-muted p-4">
          <p className="font-medium">{p("speakerQuestion")}</p>
          <div className="flex flex-wrap gap-2">
            <PillButton variant="secondary" onClick={() => void playTestTone()}>
              <Volume2 aria-hidden />
              {t("playTone")}
            </PillButton>
            <PillButton onClick={() => void finish(true)}>{t("speakerYes")}</PillButton>
            <PillButton variant="quiet" onClick={() => void finish(false)}>
              {p("speakerNo")}
            </PillButton>
          </div>
        </div>
      ) : null}

      {phase === "submitting" ? (
        <p role="status" className="text-[0.92rem] text-muted-foreground">
          {p("saving")}
        </p>
      ) : null}

      {phase === "failed" || phase === "error" ? (
        <div className="grid gap-3">
          <Notice role="alert" tone="danger">
            {error
              ? errors(error)
              : p("mustFix", {
                  items: failed.map((check) => t(`names.${check}` as "names.camera")).join(", "),
                })}
          </Notice>
          <PillButton variant="secondary" className="w-fit" onClick={() => void run()}>
            {t("again")}
          </PillButton>
        </div>
      ) : null}
    </div>
  );
}
