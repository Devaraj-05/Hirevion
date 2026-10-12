import { Button, Skeleton } from "@hirevion/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, isCommandError, type ReleaseState, type StartResult } from "../native/commands";
import {
  applyProgress,
  failureReason,
  isBusy,
  outcomeState,
  progressPercent,
  type UpdateState,
} from "./update";

/** Launch → version check (PRD §26): an outdated app stops here (contract candidate-auth). */
export function LaunchScreen({ onChecked }: { onChecked: (release: ReleaseState) => void }) {
  const t = useTranslations("launch");
  const [offline, setOffline] = useState(false);

  const check = useCallback(async () => {
    setOffline(false);
    try {
      onChecked(await commands.releaseCheck());
    } catch {
      setOffline(true);
    }
  }, [onChecked]);

  useEffect(() => {
    void check();
  }, [check]);

  return (
    <div className="grid justify-items-center gap-4 py-16 text-center">
      {offline ? (
        <>
          <p role="alert">{t("offline")}</p>
          <Button onClick={() => void check()}>{t("retry")}</Button>
        </>
      ) : (
        <>
          <Skeleton className="h-2 w-48" />
          <p className="text-muted-foreground text-sm">{t("checking")}</p>
        </>
      )}
    </div>
  );
}

/**
 * The update gate (PRD §26, master plan §6.4 step 2): "Update now" checks for the signed
 * release, downloads and installs it, and Windows restarts the app on the new version. The
 * download link stays as a fallback for a computer that can't update in place.
 */
export function UpdateRequiredScreen({
  minimumVersion,
  downloadUrl,
}: {
  minimumVersion: string | null;
  downloadUrl: string | null;
}) {
  const t = useTranslations("update");
  const [state, setState] = useState<UpdateState>({ step: "idle" });
  const busy = isBusy(state);
  // Each attempt has a number, so progress from an earlier attempt can't touch a later one.
  const attempt = useRef(0);

  async function update() {
    const mine = ++attempt.current;
    const current = () => attempt.current === mine;
    setState({ step: "checking" });
    try {
      const outcome = await commands.updateInstall((progress) => {
        if (current()) setState((previous) => applyProgress(previous, progress));
      });
      if (current()) setState(outcomeState(outcome.status));
    } catch (error) {
      if (current()) setState({ step: "failed", reason: failureReason(error) });
    }
  }

  const percent =
    state.step === "downloading" ? progressPercent(state.downloaded, state.total) : null;
  return (
    <section className="grid gap-4" aria-labelledby="update-title">
      <h1 id="update-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{minimumVersion ? t("body", { version: minimumVersion }) : t("bodyNoVersion")}</p>
      {busy ? (
        <div className="grid gap-2" role="status" aria-live="polite">
          <p className="text-sm">
            {state.step === "checking" ? t("checking") : null}
            {state.step === "downloading"
              ? percent === null
                ? t("downloadingUnknown")
                : t("downloading", { percent })
              : null}
            {state.step === "installing" ? t("installing") : null}
          </p>
          {state.step === "downloading" && percent !== null ? (
            <progress className="w-full" max={100} value={percent} aria-label={t("progress")} />
          ) : null}
        </div>
      ) : null}
      {state.step === "up-to-date" ? <p role="alert">{t("upToDate")}</p> : null}
      {state.step === "restart" ? <p role="alert">{t("restart")}</p> : null}
      {state.step === "failed" ? (
        <p role="alert" className="text-danger text-sm">
          {t(`errors.${state.reason}`)}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-4">
        <Button disabled={busy || state.step === "restart"} onClick={() => void update()}>
          {t(state.step === "failed" ? "retry" : "now")}
        </Button>
        {downloadUrl ? (
          <a
            className="w-fit font-medium underline"
            href={downloadUrl}
            target="_blank"
            rel="noreferrer"
          >
            {t("download")}
          </a>
        ) : null}
      </div>
    </section>
  );
}

/** Ready (PRD §26): every check passed and consent given; starting dispatches the AI. */
export function ReadyScreen({
  interviewId,
  systemCheckId,
  consentId,
  onStarted,
  onBack,
  onError,
}: {
  interviewId: string;
  systemCheckId: string;
  consentId: string;
  onStarted: (start: StartResult) => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("ready");
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function begin() {
    setWorking(true);
    setFailure(null);
    try {
      onStarted(await commands.start(interviewId, systemCheckId, consentId));
    } catch (error) {
      onError(error);
      setFailure(isCommandError(error) ? error.code : "unknown");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="grid gap-4" aria-labelledby="ready-title">
      <h1 id="ready-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{t("body")}</p>
      {failure ? (
        <p role="alert" className="text-danger text-sm">
          {t.has(`errors.${failure}` as "errors.unknown")
            ? t(`errors.${failure}` as "errors.unknown")
            : t("errors.unknown")}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={working} onClick={() => void begin()}>
          {working ? t("starting") : t("start")}
        </Button>
        <Button variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
    </section>
  );
}
