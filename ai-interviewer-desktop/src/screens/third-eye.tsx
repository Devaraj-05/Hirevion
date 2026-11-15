import { Button, Checkbox, Label } from "@hirevion/ui";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import type { SystemCheckPayload } from "../checks/payload";
import { commands, isCommandError, type PairingView } from "../native/commands";
import type { Framing } from "../third-eye/framing";
import { phoneState, type ThirdEyeMode } from "../third-eye/pairing";
import { PhonePreview, type Verdict } from "../third-eye/preview";
import { ErrorText } from "./shell";

/** How often the step reads the pairing's status (contract third-eye.md: every 2 s). */
const POLL_MS = 2_000;
const KNOWN_ERRORS = [
  "media-unavailable",
  "check-failed",
  "network",
  "interview-not-open",
  "third-eye-not-connected",
  "not-paired",
  "invalid-placement",
];

function errorCode(failure: unknown): string {
  const code = isCommandError(failure) ? failure.code : "unknown";
  return KNOWN_ERRORS.includes(code) ? code : "unknown";
}

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
  // The parent's props change every render; the latest are used and nothing re-pairs.
  const latest = useRef({ onDone, onError, recheck });
  useEffect(() => {
    latest.current = { onDone, onError, recheck };
  });
  // Only the newest pairing request's answer counts (a new code supersedes an old one).
  const request = useRef(0);
  const started = useRef(false);
  // On a small screen the placement card pushes the buttons down: bring Continue into view once
  // the phone connects.
  const actions = useRef<HTMLDivElement>(null);
  const connected = phoneState(status) === "connected";
  // C8-3 (owner, 2026-11-15): the phone's picture must show the candidate and their whole
  // laptop (green), and the candidate confirms it, before they can continue.
  const [verdict, setVerdict] = useState<Verdict>({ green: false, framing: null, evidence: null });
  const [confirmed, setConfirmed] = useState(false);
  const green = connected && verdict.green;
  useEffect(() => {
    if (!green) setConfirmed(false);
  }, [green]);
  useEffect(() => {
    if (green) actions.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [green]);

  /** Done with the phone: the check that waited for it is sent again first. */
  const finish = useCallback(async () => {
    const waiting = latest.current.recheck;
    if (waiting === null) {
      latest.current.onDone(null);
      return;
    }
    setWorking(true);
    setError(null);
    try {
      // The server now sees the phone's camera (or no longer needs one).
      const submitted = await commands.submitChecks(interviewId, waiting);
      if (submitted.passed) latest.current.onDone(submitted.id);
      else setError("check-failed");
    } catch (failure) {
      latest.current.onError(failure);
      setError(errorCode(failure));
    } finally {
      setWorking(false);
    }
  }, [interviewId]);

  const pair = useCallback(
    async (replace: boolean) => {
      const mine = ++request.current;
      setError(null);
      try {
        const next = await commands.thirdEyePair(interviewId, replace);
        if (mine !== request.current) return;
        setPairing(next);
        setStatus(next.status);
        setDevice(next.device);
        setCopied(false);
      } catch (failure) {
        if (mine !== request.current) return;
        latest.current.onError(failure);
        // The interview no longer uses a third eye: nothing to set up.
        if (isCommandError(failure) && failure.code === "third-eye-off") void finish();
        else setError(errorCode(failure));
      }
    },
    [interviewId, finish],
  );

  // One pairing request when the step opens (development's double mount doesn't make two:
  // a second code would revoke the first).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void pair(false);
  }, [pair]);

  // Follow this pairing (a scan, the camera, a lock, an expiry): one read at a time, and an
  // answer about another pairing is ignored.
  useEffect(() => {
    if (pairing === null) return;
    let cancelled = false;
    let timer: number | undefined;
    const read = async () => {
      try {
        const seen = await commands.thirdEyeStatus(interviewId);
        if (cancelled || seen.pairing_id !== pairing.pairing_id) return;
        setStatus(seen.status);
        setDevice(seen.device);
      } catch (failure) {
        // A lost session goes back to sign-in; anything else waits for the next read.
        if (!cancelled) latest.current.onError(failure);
      }
      if (!cancelled) timer = window.setTimeout(() => void read(), POLL_MS);
    };
    timer = window.setTimeout(() => void read(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [interviewId, pairing]);

  /** Records the confirmed placement, then moves on. */
  async function placed() {
    // The green frames' scores, not whichever frame came last.
    const seen = verdict.evidence;
    if (!green || !confirmed || !seen) return;
    setWorking(true);
    setError(null);
    try {
      await commands.thirdEyePlacement(interviewId, seen.personScore, seen.laptopScore);
    } catch (failure) {
      latest.current.onError(failure);
      setError(errorCode(failure));
      setWorking(false);
      return;
    }
    setWorking(false);
    await finish();
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

      {/* Next to the code, so a small screen shows it without scrolling. */}
      {pairing ? (
        <p role="status" aria-live="polite" className="font-medium">
          {t(`state.${phone}`, { device: device ?? t("yourPhone") })}
        </p>
      ) : null}

      {connected ? (
        <section
          className="grid gap-3 rounded-md border border-border p-4"
          aria-labelledby={`${id}-check`}
        >
          <h2 id={`${id}-check`} className="font-medium">
            {t("check.title")}
          </h2>
          <PhonePreview interviewId={interviewId} onVerdict={setVerdict} />
          <p
            role="status"
            aria-live="polite"
            className={green ? "font-medium text-success" : "font-medium text-warning"}
          >
            {t(`check.${checkMessage(verdict)}`)}
          </p>
          <div className="flex items-start gap-3">
            <Checkbox
              id={`${id}-confirm`}
              checked={confirmed}
              disabled={!green}
              onCheckedChange={(checked) => setConfirmed(checked === true)}
            />
            <Label htmlFor={`${id}-confirm`} className="font-normal">
              {t("check.confirm")}
            </Label>
          </div>
        </section>
      ) : null}

      {/* Right under the code, so the candidate reads it while placing the phone (owner, 2026-11-15). */}
      <section
        className="grid gap-2 rounded-md border border-border p-4"
        aria-labelledby={`${id}-placement`}
      >
        <h2 id={`${id}-placement`} className="font-medium">
          {t("placement.title")}
        </h2>
        <ul className="grid list-disc gap-1 pl-5 text-sm">
          <li>{t("placement.sideways")}</li>
          <li>{t("placement.side")}</li>
          <li>{t("placement.frame")}</li>
          <li>{t("placement.light")}</li>
          <li>{t("placement.steady")}</li>
          <li>{t("placement.lock")}</li>
        </ul>
      </section>

      {error ? <ErrorText>{t(`errors.${error}`)}</ErrorText> : null}

      <div ref={actions} className="flex flex-wrap gap-2">
        <Button disabled={working || !green || !confirmed} onClick={() => void placed()}>
          {t("continue")}
        </Button>
        {pairing === null && error ? (
          <Button variant="secondary" onClick={() => void pair(false)}>
            {t("retry")}
          </Button>
        ) : null}
        {pairing !== null && phone !== "connected" ? (
          // Also for a phone that scanned but never sent its camera: a new code replaces it.
          <Button
            variant={phone === "new-code" ? "secondary" : "ghost"}
            onClick={() => void pair(true)}
          >
            {t("newCode")}
          </Button>
        ) : null}
        {/* An optional phone never blocks the candidate, connected or not. */}
        {mode === "optional" ? (
          <Button variant="secondary" disabled={working} onClick={() => void finish()}>
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

/** What the status line under the phone's picture says. */
function checkMessage(verdict: Verdict): string {
  const seen: Framing | null = verdict.framing;
  if (verdict.green) return "green";
  if (seen === null) return "checking";
  if (seen.portrait) return "portrait";
  if (seen.person === "missing") return "personMissing";
  if (seen.person === "cut") return "personCut";
  if (seen.laptop === "missing") return "laptopMissing";
  if (seen.laptop === "cut") return "laptopCut";
  return "hold";
}
