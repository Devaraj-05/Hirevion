import { AppWindow, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { appsVerdict } from "../../checks/apps";
import { checkCamera } from "../../checks/camera";
import { checkMicrophone } from "../../checks/microphone";
import { networkResult } from "../../checks/network";
import type { SystemCheckPayload } from "../../checks/payload";
import { buildPayload, missingMandatory } from "../../checks/payload";
import { shownToCandidate } from "../../checks/shown";
import { playTestTone, speakerResult } from "../../checks/speaker";
import { webview2Result } from "../../checks/thresholds";
import type { CheckResult } from "../../checks/types";
import { type AppRules, type AppsToClose, commands } from "../../native/commands";
import { onlyThirdEyeFailed, type ThirdEyeMode } from "../../third-eye/pairing";
import { Notice, PillButton } from "../../ui/kit";
import { type ErrorKey, errorKey } from "../errors";
import { ResultLine, showAboveBar } from "./step";

type Phase = "running" | "speaker" | "submitting" | "apps" | "failed" | "error";

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

type AppsLook = AppsToClose | "failed" | null;

/** How long an early look at the apps stays good: the candidate may open one meanwhile. */
const APPS_FRESH_MS = 10_000;

/** The running apps `rules` block and the other open ones; null when apps aren't checked. */
async function lookAtApps(rules: AppRules | null): Promise<AppsLook> {
  if (!rules) return null;
  try {
    return await commands.appsToClose(rules);
  } catch (failure) {
    console.warn("prepare: the running apps couldn't be checked", failure);
    return "failed";
  }
}

/**
 * Step 2, PRD §29: the native checks run in Rust while the webview checks the camera, the
 * microphone (the candidate says a few words) and the network; the candidate confirms the
 * test sound; the API decides from the interview's policy whether the computer passes.
 * Then the running apps (ADR-0046): one the policy blocks must be closed before the step is
 * done; other open apps are advised closed. The look starts with the check, so its few
 * seconds pass while the candidate answers the sound question.
 */
export function ChecksStep({
  interviewId,
  thirdEye,
  appRules,
  onPassed,
  onError,
}: {
  interviewId: string;
  thirdEye: ThirdEyeMode;
  appRules: AppRules | null;
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
  const appsPanel = useRef<HTMLElement>(null);
  const looking = useRef<{ at: number; look: Promise<AppsLook> } | null>(null);
  const passed = useRef<{ id: string; payload: SystemCheckPayload; phone: boolean } | null>(null);
  const [apps, setApps] = useState<AppsLook>(null);
  const [checkingApps, setCheckingApps] = useState(false);
  // The sound question and the apps to close appear under the results: bring them into view.
  useEffect(() => {
    if (phase === "speaker") showAboveBar(question.current);
    if (phase === "apps" && !checkingApps) showAboveBar(appsPanel.current);
  }, [phase, checkingApps]);

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
    looking.current = { at: Date.now(), look: lookAtApps(appRules) };
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
        await afterChecks(submitted.id, payload, false);
        return;
      }
      if (thirdEye === "required" && onlyThirdEyeFailed(submitted.failed_mandatory)) {
        await afterChecks(submitted.id, payload, true);
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

  /** The computer passed: on to the running apps. */
  async function afterChecks(id: string, payload: SystemCheckPayload, phone: boolean) {
    passed.current = { id, payload, phone };
    setPhase("apps");
    setCheckingApps(true);
    const early = looking.current;
    const fresh = early && Date.now() - early.at < APPS_FRESH_MS;
    showApps(await (fresh ? early.look : lookAtApps(appRules)));
  }

  function showApps(found: AppsLook) {
    setCheckingApps(false);
    setApps(found);
    if (appsVerdict(found) === "clear") done();
  }

  async function checkAppsAgain() {
    setCheckingApps(true);
    showApps(await lookAtApps(appRules));
  }

  function done() {
    const result = passed.current;
    if (result) onPassed(result.id, result.payload, result.phone);
  }

  const verdict = appsVerdict(apps);
  const shown = shownToCandidate(
    buildPayload({ appVersion: "", native: results, web: [] }).results,
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

      {phase === "apps" && checkingApps ? (
        <p role="status" className="text-[0.92rem] text-muted-foreground">
          {p("appsChecking")}
        </p>
      ) : null}

      {phase === "apps" && !checkingApps && verdict !== "clear" ? (
        <section
          ref={appsPanel}
          aria-label={verdict === "close" ? p("appsCloseTitle") : p("appsAdviseTitle")}
          className="grid scroll-mb-28 gap-3 rounded-2xl bg-surface-muted p-4"
        >
          <div className="grid gap-1">
            <p className={verdict === "close" ? "font-semibold text-danger" : "font-semibold"}>
              {verdict === "close" ? p("appsCloseTitle") : p("appsAdviseTitle")}
            </p>
            <p className="text-[0.9rem] text-muted-foreground">
              {apps === "failed"
                ? p("appsFailed")
                : verdict === "close"
                  ? p("appsCloseLead")
                  : p("appsAdviseLead")}
            </p>
          </div>
          {apps && apps !== "failed" ? (
            <>
              {verdict === "close" ? <AppList apps={apps.blocked} /> : null}
              {apps.background.length > 0 ? (
                <div className="grid gap-2">
                  <p className="font-medium text-[0.9rem]">{p("appsBackground")}</p>
                  <AppList apps={apps.background} />
                </div>
              ) : null}
              {apps.open.length > 0 ? (
                <div className="grid gap-2">
                  {verdict === "close" || apps.background.length > 0 ? (
                    <p className="font-medium text-[0.9rem]">{p("appsAlso")}</p>
                  ) : null}
                  <AppList apps={apps.open} />
                </div>
              ) : null}
            </>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <PillButton onClick={() => void checkAppsAgain()}>{p("appsAgain")}</PillButton>
            {verdict === "advise" ? (
              <PillButton variant="secondary" onClick={done}>
                {p("appsContinue")}
              </PillButton>
            ) : null}
          </div>
        </section>
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

/** Running apps, each by its name and its first window's title; long names wrap. */
function AppList({ apps }: { apps: AppsToClose["open"] }) {
  return (
    <ul className="grid gap-2">
      {apps.map((app) => (
        <li key={app.name} className="flex min-w-0 items-start gap-2.5">
          <AppWindow className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 break-words text-[0.92rem]">
            <span className="font-medium">{appName(app.name)}</span>
            {app.window_title ? (
              <span className="text-muted-foreground"> · {app.window_title}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function appName(file: string): string {
  return file.toLowerCase().endsWith(".exe") ? file.slice(0, -4) : file;
}
