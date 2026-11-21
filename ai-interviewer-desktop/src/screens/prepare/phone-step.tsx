import { Checkbox, cn, Label } from "@hirevion/ui";
import { BatteryCharging, Lightbulb, MonitorSmartphone, RotateCw, ScanEye } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import type { SystemCheckPayload } from "../../checks/payload";
import { commands, isCommandError, type PairingView } from "../../native/commands";
import { phoneState } from "../../third-eye/pairing";
import { PhonePreview } from "../../third-eye/preview";
import { checkMessage, type Verdict } from "../../third-eye/verdict";
import { Notice, PillButton } from "../../ui/kit";
import { showAboveBar } from "./step";

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

/** Where the phone goes, in the order the candidate does it (owner, 2026-11-15). */
const PLACEMENT = [
  { key: "side", icon: MonitorSmartphone },
  { key: "sideways", icon: RotateCw },
  { key: "frame", icon: ScanEye },
  { key: "light", icon: Lightbulb },
  { key: "steady", icon: BatteryCharging },
] as const;

/**
 * Step 4, §6.4: the candidate scans a code with their phone, which becomes the interview's
 * second camera, places it, and confirms the picture once it is green (C8-3): them and their
 * whole laptop, nobody and no other laptop. Rust issues the code and reads the pairing (the
 * webview never holds a session token). A check that failed only on the third eye (`recheck`)
 * is sent again once the phone is in place.
 */
export function PhoneStep({
  interviewId,
  mode,
  recheck,
  onDone,
  onError,
}: {
  interviewId: string;
  mode: "optional" | "required";
  recheck: SystemCheckPayload | null;
  /** The phone is in place (or skipped); a new passing system check's id when one was sent. */
  onDone: (systemCheckId: string | null) => void;
  onError: (error: unknown) => void;
}) {
  const t = useTranslations("thirdEye");
  const p = useTranslations("prepare.phone");
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
  const connected = phoneState(status) === "connected";
  const [verdict, setVerdict] = useState<Verdict>({ green: false, framing: null, evidence: null });
  const [confirmed, setConfirmed] = useState(false);
  const green = connected && verdict.green;
  const confirm = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!green) setConfirmed(false);
    // Green: bring the confirmation into view, above the Start bar.
    else showAboveBar(confirm.current);
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
  const message = checkMessage(verdict);
  return (
    <div className="grid gap-5">
      {connected ? (
        <div className="grid gap-4">
          <PhonePreview interviewId={interviewId} onVerdict={setVerdict} />
          <p
            role="status"
            aria-live="polite"
            className={cn(
              "flex items-center gap-2 font-medium",
              green ? "text-success" : "text-warning",
            )}
          >
            <span
              aria-hidden
              className={cn("size-2 rounded-full", green ? "bg-success" : "bg-warning")}
            />
            {t(`check.${message}`)}
          </p>
          <div
            ref={confirm}
            className="flex scroll-mb-28 items-start gap-3 rounded-2xl bg-surface-muted p-4"
          >
            <Checkbox
              id={`${id}-confirm`}
              className="mt-0.5 size-5 rounded-md"
              checked={confirmed}
              disabled={!green}
              onCheckedChange={(checked) => setConfirmed(checked === true)}
            />
            <div className="grid gap-1">
              <Label htmlFor={`${id}-confirm`} className="font-medium text-[0.95rem]">
                {t("check.confirm")}
              </Label>
              {!green ? (
                <p className="text-[0.85rem] text-muted-foreground">{t("check.confirmHint")}</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
          <figure className="grid h-fit justify-items-center gap-3 rounded-2xl border border-border/70 bg-white p-5 text-center text-[#1d1d1f]">
            {qr && phone === "waiting" ? (
              <svg
                viewBox={`0 0 ${qr.size} ${qr.size}`}
                role="img"
                aria-label={t("qrLabel")}
                className="size-48"
                shapeRendering="crispEdges"
              >
                <path d={qr.path} fill="#1d1d1f" />
              </svg>
            ) : (
              <div className="grid size-48 place-items-center text-[0.9rem] text-[#63636a]">
                {pairing ? t(`state.${phone}`, { device: device ?? t("yourPhone") }) : p("making")}
              </div>
            )}
            <figcaption className="max-w-48 text-[0.85rem] text-[#63636a]">{p("scan")}</figcaption>
          </figure>
          {/* min-w-0: a long link never widens the column past the card (owner, 2026-11-21). */}
          <div className="grid h-fit min-w-0 gap-4">
            <h3 className="font-semibold">{t("placement.title")}</h3>
            <ol className="grid gap-3">
              {PLACEMENT.map(({ key, icon: Icon }) => (
                <li key={key} className="flex items-start gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-subtle text-accent-subtle-foreground">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 pt-1 text-[0.92rem] leading-snug">
                    {p(`placement.${key}`)}
                  </span>
                </li>
              ))}
            </ol>
            {link && phone === "waiting" ? (
              <p className="grid min-w-0 justify-items-start gap-1.5 text-[0.85rem] text-muted-foreground">
                {p("link")}
                {/* The whole link, wrapped: a candidate may have to type it on the phone. */}
                <code className="max-w-full break-all rounded-md bg-surface-sunken px-2 py-1 text-foreground">
                  {link}
                </code>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => void copyLink(link)}
                >
                  {copied ? t("copied") : t("copy")}
                </button>
              </p>
            ) : null}
          </div>
        </div>
      )}

      {pairing && phone !== "waiting" && !connected ? (
        <p role="status" aria-live="polite" className="font-medium">
          {t(`state.${phone}`, { device: device ?? t("yourPhone") })}
        </p>
      ) : null}

      {error ? (
        <Notice role="alert" tone="danger">
          {t(`errors.${error}`)}
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {connected ? (
          <PillButton disabled={working || !green || !confirmed} onClick={() => void placed()}>
            {p("done")}
          </PillButton>
        ) : null}
        {pairing === null && error ? (
          <PillButton variant="secondary" onClick={() => void pair(false)}>
            {t("retry")}
          </PillButton>
        ) : null}
        {pairing !== null && !connected ? (
          // Also for a phone that scanned but never sent its camera: a new code replaces it.
          <PillButton
            variant={phone === "new-code" ? "primary" : "quiet"}
            onClick={() => void pair(true)}
          >
            {t("newCode")}
          </PillButton>
        ) : null}
        {/* An optional phone never blocks the candidate, connected or not. */}
        {mode === "optional" ? (
          <PillButton variant="quiet" disabled={working} onClick={() => void finish()}>
            {t("skip")}
          </PillButton>
        ) : null}
      </div>
    </div>
  );
}
