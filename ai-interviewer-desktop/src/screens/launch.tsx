import { Button, Skeleton } from "@hirevion/ui";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, isCommandError, type ReleaseState, type StartResult } from "../native/commands";

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

export function UpdateRequiredScreen({
  minimumVersion,
  downloadUrl,
}: {
  minimumVersion: string | null;
  downloadUrl: string | null;
}) {
  const t = useTranslations("update");
  return (
    <section className="grid gap-4" aria-labelledby="update-title">
      <h1 id="update-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{minimumVersion ? t("body", { version: minimumVersion }) : t("bodyNoVersion")}</p>
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
