import { Button } from "@hirevion/ui";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import type { SystemCheckPayload } from "../checks/payload";
import { commands, isCommandError, type PairingView } from "../native/commands";
import { canContinue, phoneState, type ThirdEyeMode } from "../third-eye/pairing";
import { ErrorText } from "./shell";

/** How often the step reads the pairing's status (contract third-eye.md: every 2 s). */
const POLL_MS = 2_000;
const KNOWN_ERRORS = ["media-unavailable", "check-failed", "network", "interview-not-open"];

/**
 * §6.4's phone step: the candidate scans a code with their phone, which becomes the interview's
 * second camera. Rust issues the code and reads the pairing (the webview never holds a session
 * token); the server judges the camera from its own view. A check that failed only on the
 * third eye (`recheck`) is sent again once the phone is connected.
 */
export function ThirdEyeScreen({
  interviewId,
  mode,
  recheck,
  onDone,
  onBack,
  onError,
}: {
  interviewId: string;
  mode: Exclude<ThirdEyeMode, "off">;
  recheck: SystemCheckPayload | null;
  /** The phone step is done; a new passing system check's id when one was sent again. */
  onDone: (systemCheckId: string | null) => void;
  onBack: () => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("thirdEye");
  const id = useId();
  const [pairing, setPairing] = useState<PairingView | null>(null);
  const [status, setStatus] = useState("issued");
  const [device, setDevice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);
  // The parent's callbacks change every render; the latest is called, nothing re-pairs.
  const latest = useRef({ onDone, onError });
  useEffect(() => {
    latest.current = { onDone, onError };
  });

  const pair = useCallback(
    async (replace: boolean) => {
      setError(null);
      try {
        const next = await commands.thirdEyePair(interviewId, replace);
        setPairing(next);
        setStatus(next.status);
        setDevice(next.device);
      } catch (failure) {
        latest.current.onError(failure);
        const code = isCommandError(failure) ? failure.code : "unknown";
        // The interview no longer uses a third eye: nothing to set up.
        if (code === "third-eye-off") latest.current.onDone(null);
        else setError(KNOWN_ERRORS.includes(code) ? code : "unknown");
      }
    },
    [interviewId],
  );

  useEffect(() => {
    void pair(false);
  }, [pair]);

  // Follow the pairing while the step is open (a scan, the camera, a lock, an expiry).
  useEffect(() => {
    if (pairing === null) return;
    const timer = window.setInterval(() => {
      commands
        .thirdEyeStatus(interviewId)
        .then((seen) => {
          setStatus(seen.status);
          setDevice(seen.device);
        })
        .catch(() => undefined); // The next read may work; the last status stays.
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [interviewId, pairing]);

  async function goOn() {
    if (recheck === null) {
      latest.current.onDone(null);
      return;
    }
    setWorking(true);
    setError(null);
    try {
      // The check that waited for the phone: the server now sees the phone's camera.
      const submitted = await commands.submitChecks(interviewId, recheck);
      if (submitted.passed) latest.current.onDone(submitted.id);
      else setError("check-failed");
    } catch (failure) {
      latest.current.onError(failure);
      const code = isCommandError(failure) ? failure.code : "unknown";
      setError(KNOWN_ERRORS.includes(code) ? code : "unknown");
    } finally {
      setWorking(false);
    }
  }

  async function copyLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const phone = phoneState(status);
  const qr = pairing?.qr ?? null;
  const link = pairing?.link ?? null;
  return (
    <section className="grid gap-5" aria-labelledby={`${id}-title`}>
      <div className="grid gap-1">
        <h1 id={`${id}-title`} className="font-semibold text-2xl">
          {t("title")}
        </h1>
        <p className="text-muted-foreground text-sm">
          {mode === "required" ? t("introRequired") : t("introOptional")}
        </p>
      </div>

      {phone === "waiting" && qr ? (
        <figure className="grid w-fit gap-3">
          <svg
            viewBox={`0 0 ${qr.size} ${qr.size}`}
            role="img"
            aria-label={t("qrLabel")}
            className="size-56 rounded-md bg-white"
            shapeRendering="crispEdges"
          >
            <path d={qr.path} fill="#000" />
          </svg>
          <figcaption className="grid gap-2 text-sm">
            <span>{t("scan")}</span>
            {link ? (
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground">{t("orType")}</span>
                <code className="break-all rounded bg-surface-sunken px-1">{link}</code>
                <Button variant="ghost" size="sm" onClick={() => void copyLink(link)}>
                  {copied ? t("copied") : t("copy")}
                </Button>
              </span>
            ) : null}
          </figcaption>
        </figure>
      ) : null}

      <p role="status" aria-live="polite" className="font-medium">
        {t(`state.${phone}`, { device: device ?? t("yourPhone") })}
      </p>

      <ul className="grid list-disc gap-1 pl-5 text-sm">
        <li>{t("placement.where")}</li>
        <li>{t("placement.power")}</li>
        <li>{t("placement.lock")}</li>
      </ul>

      {phone === "new-code" ? (
        <Button variant="secondary" className="w-fit" onClick={() => void pair(true)}>
          {t("newCode")}
        </Button>
      ) : null}

      {error ? <ErrorText>{t(`errors.${error}`)}</ErrorText> : null}

      <div className="flex flex-wrap gap-2">
        <Button disabled={working || phone !== "connected"} onClick={() => void goOn()}>
          {t("continue")}
        </Button>
        {mode === "optional" && canContinue(status, mode) && phone !== "connected" ? (
          <Button variant="secondary" onClick={() => latest.current.onDone(null)}>
            {t("skip")}
          </Button>
        ) : null}
        <Button variant="ghost" onClick={onBack}>
          {t("back")}
        </Button>
      </div>
    </section>
  );
}
