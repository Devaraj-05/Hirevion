import { cn } from "@hirevion/ui";
import { Smartphone, Video } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import type { Health } from "../../interview/health";
import { Emblem } from "../../ui/emblem";

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

const DOTS: Record<TileStatus, string> = {
  starting: "bg-warning",
  ok: "bg-success",
  problem: "bg-danger",
  off: "bg-muted-foreground",
};

/**
 * One camera (C8-12): the candidate's webcam (mirrored, as in a mirror) or the phone beside the
 * laptop. A label, a live dot with its words, and a "CONFIDENTIAL • INTERVIEW SESSION" mark
 * along the bottom edge, drawn over the picture only: the recorded tracks stay clean.
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
    <figure className="camera-tile" data-kind={kind} data-status={status}>
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
          <Icon aria-hidden className="size-5" strokeWidth={1.75} />
          <p>{note}</p>
        </div>
      )}
      <figcaption className="camera-chip">{t(`${kind}.label`)}</figcaption>
      <span className="camera-status">
        <span aria-hidden className={cn("size-1.5 rounded-full", DOTS[status])} />
        {t(`status.${status}`)}
      </span>
      <span className="camera-watermark" aria-hidden>
        <Emblem tone="light" className="size-3.5" />
        {t("watermark")}
      </span>
    </figure>
  );
}
