import { Camera, Mic } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { Notice, PillButton } from "../../ui/kit";
import { showAboveBar } from "./step";

type Access = "idle" | "asking" | "granted" | "blocked" | "missing";

/** How loud the microphone is, 0 to 1, read from the analyser's samples. */
function loudness(analyser: AnalyserNode, samples: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(samples);
  let peak = 0;
  for (const value of samples) peak = Math.max(peak, Math.abs(value));
  // About -60 dBFS (silence) to -6 dBFS (a raised voice).
  const db = 20 * Math.log10(Math.max(peak, 1e-6));
  return Math.min(1, Math.max(0, (db + 60) / 54));
}

/**
 * Step 1: the candidate allows the camera and the microphone, sees themselves and their voice
 * move the meter, then goes on. Windows asks once for this app; the devices are let go when the
 * step is done, so the system check opens them afresh.
 */
export function DevicesStep({ onDone }: { onDone: () => void }) {
  const t = useTranslations("prepare.devices");
  const [access, setAccess] = useState<Access>("idle");
  const [level, setLevel] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const seen = useRef<HTMLDivElement>(null);
  const stream = useRef<MediaStream | null>(null);

  async function ask() {
    setAccess("asking");
    try {
      const opened = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      // The candidate left while Windows asked: let the camera and microphone go at once.
      if (!mounted.current) {
        for (const track of opened.getTracks()) track.stop();
        return;
      }
      stream.current = opened;
      setAccess("granted");
    } catch (error) {
      const name = error instanceof DOMException ? error.name : "";
      setAccess(
        name === "NotFoundError" || name === "OverconstrainedError" ? "missing" : "blocked",
      );
    }
  }

  // The picture and the meter, while access is granted.
  useEffect(() => {
    const opened = stream.current;
    if (access !== "granted" || !opened) return;
    if (video.current) video.current.srcObject = opened;
    // The picture and Continue come into view, above the Start bar.
    showAboveBar(seen.current);
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(opened).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let frame = 0;
    const read = () => {
      setLevel((previous) => Math.max(loudness(analyser, samples), previous * 0.85));
      frame = requestAnimationFrame(read);
    };
    frame = requestAnimationFrame(read);
    return () => {
      cancelAnimationFrame(frame);
      void context.close();
    };
  }, [access]);

  // Let the camera and microphone go when the step closes.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const track of stream.current?.getTracks() ?? []) track.stop();
      stream.current = null;
    };
  }, []);

  return (
    <div className="grid gap-5">
      {access === "granted" ? (
        <div
          ref={seen}
          className="grid scroll-mb-28 gap-4 sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] sm:items-end"
        >
          <video
            ref={video}
            autoPlay
            muted
            playsInline
            aria-label={t("preview")}
            className="aspect-video w-full -scale-x-100 rounded-2xl bg-black object-cover"
          />
          <div className="grid gap-3">
            <p className="flex items-center gap-2 font-medium text-[0.95rem]">
              <Mic className="size-4 text-muted-foreground" aria-hidden />
              {t("speak")}
            </p>
            <meter
              min={0}
              max={1}
              value={level}
              aria-label={t("level")}
              className="h-2 w-full overflow-hidden rounded-full [&::-webkit-meter-bar]:rounded-full [&::-webkit-meter-bar]:border-0 [&::-webkit-meter-bar]:bg-surface-sunken [&::-webkit-meter-optimum-value]:rounded-full [&::-webkit-meter-optimum-value]:bg-success"
            />
            <PillButton className="mt-2 w-fit" onClick={onDone}>
              {t("continue")}
            </PillButton>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-4">
          <span className="flex items-center gap-3 text-muted-foreground">
            <Camera className="size-5" aria-hidden />
            <Mic className="size-5" aria-hidden />
          </span>
          <PillButton disabled={access === "asking"} onClick={() => void ask()}>
            {access === "asking" ? t("asking") : access === "idle" ? t("allow") : t("again")}
          </PillButton>
        </div>
      )}
      {access === "blocked" ? (
        <Notice role="alert" tone="danger">
          {t("blocked")}
        </Notice>
      ) : null}
      {access === "missing" ? (
        <Notice role="alert" tone="danger">
          {t("missing")}
        </Notice>
      ) : null}
    </div>
  );
}
