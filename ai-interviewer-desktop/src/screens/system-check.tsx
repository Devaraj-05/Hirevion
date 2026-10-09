import { Badge, type BadgeTone, Button } from "@hirevion/ui";
import { useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { checkCamera } from "../checks/camera";
import { checkMicrophone } from "../checks/microphone";
import { networkResult } from "../checks/network";
import { buildPayload, missingMandatory } from "../checks/payload";
import { playTestTone, speakerResult } from "../checks/speaker";
import { webview2Result } from "../checks/thresholds";
import type { CheckResult, Status } from "../checks/types";
import { commands } from "../native/commands";
import { type ErrorKey, errorKey } from "./errors";
import { ErrorText } from "./shell";

const TONES: Record<Status, BadgeTone> = {
  pass: "success",
  warn: "warning",
  fail: "danger",
  skipped: "neutral",
};
type Phase = "idle" | "running" | "speaker" | "submitting" | "done";

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
 * PRD §29: the native checks run in Rust while the webview checks the camera, the microphone
 * (the candidate speaks for 3 s) and the network; the candidate confirms the test tone; then the
 * results go to the API, which decides from the interview's policy whether they pass.
 */
export function SystemCheckScreen({
  interviewId,
  onPassed,
  onBack,
  onError,
}: {
  interviewId: string;
  onPassed: () => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("checks");
  const errors = useTranslations("errors");
  const [phase, setPhase] = useState<Phase>("idle");
  const [results, setResults] = useState<CheckResult[]>([]);
  const [level, setLevel] = useState<number | null>(null);
  const [failed, setFailed] = useState<string[]>([]);
  const [error, setError] = useState<ErrorKey | null>(null);
  const appVersion = useRef<string>("unknown");

  async function run() {
    setPhase("running");
    setError(null);
    setFailed([]);
    setResults([]);
    const info = await commands.appInfo().catch(() => null);
    appVersion.current = info?.version ?? "unknown";
    const native = nativeResults();
    const web: CheckResult[] = [webview2Result(navigator.userAgent), await network()];
    web.push(await checkCamera());
    web.push(await checkMicrophone({ onLevel: setLevel }));
    setLevel(null);
    const all = [...(await native), ...web];
    setResults(all);
    setPhase("speaker");
  }

  async function finish(heardTone: boolean) {
    const all = [...results, speakerResult(heardTone)];
    setResults(all);
    setPhase("submitting");
    const payload = buildPayload({ appVersion: appVersion.current, native: all, web: [] });
    try {
      const submitted = await commands.submitChecks(interviewId, payload);
      setFailed(submitted.failed_mandatory);
      setPhase("done");
      if (submitted.passed) onPassed();
    } catch (failure) {
      onError(failure);
      setFailed(missingMandatory(payload.results));
      setError(errorKey(failure));
      setPhase("done");
    }
  }

  const shown = buildPayload({ appVersion: "", native: results, web: [] }).results.filter(
    (result) => result.status !== "skipped" || result.check !== "third_eye" || phase === "done",
  );
  return (
    <section className="grid gap-5" aria-labelledby="checks-title">
      <div className="grid gap-1">
        <h1 id="checks-title" className="font-semibold text-2xl">
          {t("title")}
        </h1>
        <p className="text-muted-foreground text-sm">{t("intro")}</p>
      </div>
      {results.length > 0 ? (
        <ul className="grid gap-2" aria-label={t("title")}>
          {shown.map((result) => (
            <li
              key={result.check}
              className="grid gap-0.5 rounded-md border border-border p-3 text-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{t(`names.${result.check}` as "names.camera")}</span>
                <Badge tone={TONES[result.status]}>{t(`statuses.${result.status}`)}</Badge>
              </div>
              {result.value ? <span className="text-muted-foreground">{result.value}</span> : null}
              {result.detail ? <span>{result.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {phase === "running" && level !== null ? (
        <meter
          className="w-full"
          min={-80}
          max={0}
          value={Math.max(-80, level)}
          aria-label={t("names.microphone")}
        />
      ) : null}
      {phase === "speaker" ? (
        <div className="grid gap-3 rounded-md border border-border p-4">
          <Button variant="secondary" className="w-fit" onClick={() => void playTestTone()}>
            {t("playTone")}
          </Button>
          <p className="font-medium">{t("speakerQuestion")}</p>
          <div className="flex gap-2">
            <Button onClick={() => void finish(true)}>{t("speakerYes")}</Button>
            <Button variant="ghost" onClick={() => void finish(false)}>
              {t("speakerNo")}
            </Button>
          </div>
        </div>
      ) : null}
      {phase === "done" && failed.length > 0 ? <ErrorText>{t("mustFix")}</ErrorText> : null}
      {phase === "done" && failed.length === 0 && !error ? <p>{t("allPassed")}</p> : null}
      {error ? <ErrorText>{errors(error)}</ErrorText> : null}
      <div className="flex flex-wrap gap-2">
        {phase === "idle" || phase === "done" ? (
          <Button onClick={() => void run()}>{phase === "idle" ? t("run") : t("again")}</Button>
        ) : null}
        {phase === "running" || phase === "submitting" ? (
          <Button disabled>{t("running")}</Button>
        ) : null}
        <Button variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
    </section>
  );
}
