import { ArrowDownToLine, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, type ReleaseState } from "../native/commands";
import { Notice, Panel, PillButton, ScreenTitle } from "../ui/kit";
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
    <div className="m-auto grid justify-items-center gap-5 text-center">
      {offline ? (
        <>
          <WifiOff className="size-10 text-muted-foreground" strokeWidth={1.5} aria-hidden />
          <p role="alert" className="max-w-sm">
            {t("offline")}
          </p>
          <PillButton onClick={() => void check()}>{t("retry")}</PillButton>
        </>
      ) : (
        <>
          <span
            aria-hidden
            className="size-8 animate-spin rounded-full border-[2.5px] border-surface-sunken border-t-accent motion-reduce:animate-none"
          />
          <p role="status" className="text-[0.92rem] text-muted-foreground">
            {t("checking")}
          </p>
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
    <section className="m-auto w-full max-w-lg" aria-labelledby="update-title">
      <Panel className="grid gap-6 p-8">
        <ArrowDownToLine className="size-10 text-accent" strokeWidth={1.5} aria-hidden />
        <ScreenTitle
          id="update-title"
          title={t("title")}
          lead={minimumVersion ? t("body", { version: minimumVersion }) : t("bodyNoVersion")}
        />
        {busy ? (
          <div className="grid gap-2" role="status" aria-live="polite">
            <p className="text-[0.92rem] text-muted-foreground">
              {state.step === "checking" ? t("checking") : null}
              {state.step === "downloading"
                ? percent === null
                  ? t("downloadingUnknown")
                  : t("downloading", { percent })
                : null}
              {state.step === "installing" ? t("installing") : null}
            </p>
            {state.step === "downloading" && percent !== null ? (
              <progress
                className="h-1.5 w-full overflow-hidden rounded-full accent-accent"
                max={100}
                value={percent}
                aria-label={t("progress")}
              />
            ) : null}
          </div>
        ) : null}
        {state.step === "up-to-date" ? <Notice role="alert">{t("upToDate")}</Notice> : null}
        {state.step === "restart" ? (
          <Notice role="alert" tone="success">
            {t("restart")}
          </Notice>
        ) : null}
        {state.step === "failed" ? (
          <Notice role="alert" tone="danger">
            {t(`errors.${state.reason}`)}
          </Notice>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <PillButton disabled={busy || state.step === "restart"} onClick={() => void update()}>
            {t(state.step === "failed" ? "retry" : "now")}
          </PillButton>
          {downloadUrl ? (
            <a
              className="text-[0.92rem] text-accent hover:underline"
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
            >
              {t("download")}
            </a>
          ) : null}
        </div>
      </Panel>
    </section>
  );
}
