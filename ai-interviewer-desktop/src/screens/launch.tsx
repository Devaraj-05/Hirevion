import { Button, Skeleton } from "@hirevion/ui";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "use-intl";
import { commands, type ReleaseState } from "../native/commands";

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

export function ReadyScreen({ onBack }: { onBack: () => void }) {
  const t = useTranslations("ready");
  return (
    <section className="grid gap-4" aria-labelledby="ready-title">
      <h1 id="ready-title" className="font-semibold text-2xl">
        {t("title")}
      </h1>
      <p>{t("body")}</p>
      <Button variant="secondary" className="w-fit" onClick={onBack}>
        {t("back")}
      </Button>
    </section>
  );
}
