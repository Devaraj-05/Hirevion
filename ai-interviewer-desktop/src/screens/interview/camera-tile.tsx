import { cn } from "@hirevion/ui";
import { Smartphone, Video } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import type { Health } from "../../interview/health";

/** Anything that can show itself in a `<video>`: a LiveKit track, or a plain camera track. */
export interface VideoSource {
  attach(element: HTMLVideoElement): unknown;
  detach(element: HTMLVideoElement): unknown;
}

/** A camera the app opened itself (text mode), shown like a LiveKit track. */
export function mediaSource(track: MediaStreamTrack): VideoSource {
  return {
    attach: (element) => {
      element.srcObject = new MediaStream([track]);
    },
    detach: (element) => {
      element.srcObject = null;
    },
  };
}

export type TileStatus = Health | "off";

const TONES: Record<TileStatus, string> = {
  starting: "text-warning",
  ok: "text-success",
  problem: "text-danger",
  off: "text-muted-foreground",
};

/**
 * One camera (C8-12, owner's reference 2026-11-24): a card with the camera's name and whether it
 * is live, then the picture, the candidate's webcam mirrored as in a mirror, or the phone beside
 * the laptop. A "CONFIDENTIAL • INTERVIEW SESSION" mark sits on the picture's corner, drawn over
 * the picture only: the recorded tracks stay clean.
 */
export function CameraTile({
  kind,
  source,
  status,
  note,
}: {
  kind: "main" | "side";
  source: VideoSource | null;
  status: TileStatus;
  /** What to say when there's no picture to show. */
  note: string;
}) {
  const t = useTranslations("interview.cameras");
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const element = video.current;
    if (!element || !source) return;
    source.attach(element);
    void element.play().catch(() => undefined);
    return () => void source.detach(element);
  }, [source]);

  const Icon = kind === "main" ? Video : Smartphone;
  return (
    <figure className="card camera-tile" data-kind={kind} data-status={status}>
      <figcaption className="card-header camera-header">
        <Icon aria-hidden className="size-5 text-foreground" strokeWidth={2} />
        <span className="card-title">{t(`${kind}.label`)}</span>
        <span className={cn("camera-status", TONES[status])}>
          <span aria-hidden className="status-dot bg-current" />
          {t(`status.${status}`)}
        </span>
      </figcaption>
      <div className="camera-frame">
        {source ? (
          <video
            ref={video}
            className={cn("camera-video", kind === "main" && "camera-mirrored")}
            autoPlay
            muted
            playsInline
            aria-label={t(`${kind}.video`)}
          />
        ) : (
          <div className="camera-empty">
            <Icon aria-hidden className="size-6" strokeWidth={1.5} />
            <p>{note}</p>
          </div>
        )}
        <span className="camera-watermark" aria-hidden>
          {t("watermark")}
        </span>
      </div>
    </figure>
  );
}
