"use client";

import { Button } from "@hirevion/ui";
import { Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { MediaTrack, ReviewMedia } from "./api";
import { clock, filePosition, hasRecording, offsetFromFile, type TrackTiming } from "./sync";

/** How far a follower may drift from the leader before it is moved back (milliseconds). */
const DRIFT_MS = 400;
/** How often the clock moves on its own where no recording has anything (milliseconds). */
const GAP_TICK_MS = 250;
/** The links last five minutes. A file that fails after four was most likely waiting on an
 * expired link; sooner than that the file itself is the problem and fresh links won't fix it. */
const LINK_EXPIRY_MS = 4 * 60 * 1000;

interface PlayerProps {
  media: ReviewMedia;
  /** When the links were issued (milliseconds since the epoch). */
  linksIssuedAt: number;
  /** The interview's clock, in milliseconds from its start. */
  offset: number;
  playing: boolean;
  /** Changes whenever the reviewer jumps or drags: every track moves to `offset`. */
  seekRevision: number;
  end: number;
  onOffset: (offset: number) => void;
  onSeek: (offset: number) => void;
  onPlayingChange: (playing: boolean) => void;
  /** A file stopped loading because its five-minute link ran out: ask for fresh links. */
  onExpired: () => void;
}

const timing = (track: MediaTrack): TrackTiming => ({
  started_at: track.started_at ?? null,
  duration_ms: track.duration_ms ?? null,
  timeline: track.timeline ?? null,
});

/**
 * Camera, screen, third eye and audio on one timeline (PRD §71). The recording that has
 * something at the current moment leads (a camera before audio); the others follow, each placed
 * by its own timeline map, and rest where it has nothing recorded. Where none has anything the
 * clock moves on its own, so a recording that begins a few seconds late still plays. Jumping to a
 * transcript line, an event or a quote moves them all.
 */
export function MediaPlayer({
  media,
  linksIssuedAt,
  offset,
  playing,
  seekRevision,
  end,
  onOffset,
  onSeek,
  onPlayingChange,
  onExpired,
}: PlayerProps) {
  const t = useTranslations("review.player");
  const sliderId = useId();
  const elements = useRef(new Map<string, HTMLMediaElement>());
  const offsetRef = useRef(offset);
  offsetRef.current = offset;
  const [failed, setFailed] = useState<ReadonlySet<string>>(new Set());
  const tracks = media.tracks;
  const playable = useMemo(
    () => tracks.filter((track) => track.url && !failed.has(track.track)),
    [tracks, failed],
  );
  const leader = playable.find((track) => track.kind !== "audio") ?? playable[0];

  // Fresh links give every file another try.
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new `media` is the trigger.
  useEffect(() => {
    setFailed(new Set());
  }, [media]);

  const place = useCallback(
    (track: MediaTrack, at: number, play: boolean) => {
      const element = elements.current.get(track.track);
      if (!element) return;
      const position = filePosition(media.anchor, at, timing(track));
      if (position === null) {
        element.pause();
        return;
      }
      if (Math.abs(element.currentTime * 1000 - position) > DRIFT_MS) {
        element.currentTime = position / 1000;
      }
      if (play && element.paused) void element.play().catch(() => onPlayingChange(false));
    },
    [media.anchor, onPlayingChange],
  );

  // A jump or a drag: every track goes to the new position.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a new seek moves the tracks.
  useEffect(() => {
    for (const track of playable) {
      const element = elements.current.get(track.track);
      if (!element) continue;
      const position = filePosition(media.anchor, offset, timing(track));
      if (position === null) element.pause();
      else element.currentTime = position / 1000;
    }
  }, [seekRevision]);

  // Play and pause every track that has something to play.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `place` follows the latest offset on purpose.
  useEffect(() => {
    for (const track of playable) {
      if (playing) place(track, offset, true);
      else elements.current.get(track.track)?.pause();
    }
  }, [playing, seekRevision]);

  // Where no recording has anything, the clock moves by itself until one begins.
  const inGap =
    playing && playable.length > 0 && !hasRecording(media.anchor, offset, playable.map(timing));
  useEffect(() => {
    if (!inGap) return;
    const timer = window.setInterval(() => {
      const next = Math.min(offsetRef.current + GAP_TICK_MS, end);
      onOffset(next);
      for (const track of playable) place(track, next, true);
      if (next >= end) onPlayingChange(false);
    }, GAP_TICK_MS);
    return () => window.clearInterval(timer);
  }, [inGap, end, playable, place, onOffset, onPlayingChange]);

  /** The track whose own clock moves the interview's: the first with something at `at`. */
  function clockLeader(at: number): MediaTrack | undefined {
    const recorded = playable.filter(
      (track) => filePosition(media.anchor, at, timing(track)) !== null,
    );
    return recorded.find((track) => track.kind !== "audio") ?? recorded[0];
  }

  function followLeader(track: MediaTrack) {
    if (track.track !== clockLeader(offsetRef.current)?.track) return;
    const element = elements.current.get(track.track);
    if (!element) return;
    const at = offsetFromFile(media.anchor, element.currentTime * 1000, timing(track));
    if (at === null) return;
    onOffset(at);
    for (const other of playable) {
      if (other.track !== track.track) place(other, at, playing);
    }
    if (at >= end) onPlayingChange(false);
  }

  function failedToLoad(track: MediaTrack) {
    if (Date.now() - linksIssuedAt >= LINK_EXPIRY_MS) onExpired();
    else setFailed((current) => new Set(current).add(track.track));
  }

  if (tracks.length === 0) {
    return (
      <section aria-label={t("title")} className="rounded-lg border border-border p-4">
        <h2 className="mb-2 font-semibold text-base">{t("title")}</h2>
        <p className="text-muted-foreground text-sm">{t("none")}</p>
      </section>
    );
  }
  return (
    <section aria-label={t("title")} className="grid gap-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold text-base">{t("title")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {tracks.map((track) => {
          const loads = Boolean(track.url) && !failed.has(track.track);
          const position = loads ? filePosition(media.anchor, offset, timing(track)) : null;
          return (
            <figure key={track.track} className="grid gap-1" data-track={track.track}>
              <figcaption className="flex items-center justify-between text-sm">
                <span className="font-medium">{track.label}</span>
                {loads && position === null ? (
                  <span className="text-muted-foreground text-xs">{t("nothingHere")}</span>
                ) : null}
              </figcaption>
              {loads ? (
                track.kind === "audio" ? (
                  // biome-ignore lint/a11y/useMediaCaption: the transcript beside the player is the text alternative.
                  <audio
                    ref={(node) => {
                      if (node) elements.current.set(track.track, node);
                      else elements.current.delete(track.track);
                    }}
                    src={track.url ?? undefined}
                    preload="metadata"
                    onTimeUpdate={() => followLeader(track)}
                    onError={() => failedToLoad(track)}
                    aria-label={track.label}
                  />
                ) : (
                  <video
                    ref={(node) => {
                      if (node) elements.current.set(track.track, node);
                      else elements.current.delete(track.track);
                    }}
                    src={track.url ?? undefined}
                    preload="metadata"
                    muted={track.track !== leader?.track}
                    playsInline
                    onTimeUpdate={() => followLeader(track)}
                    onError={() => failedToLoad(track)}
                    aria-label={track.label}
                    className="aspect-video w-full rounded-md bg-surface-sunken"
                  />
                )
              ) : (
                <p className="rounded-md bg-surface-sunken p-3 text-muted-foreground text-xs">
                  {failed.has(track.track)
                    ? t("failed")
                    : track.stalled
                      ? t("stalled")
                      : t("preparing", { status: track.status })}
                </p>
              )}
            </figure>
          );
        })}
      </div>
      {playable.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("notReady")}</p>
      ) : (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onPlayingChange(!playing)}
            aria-label={playing ? t("pause") : t("play")}
          >
            {playing ? (
              <Pause aria-hidden className="size-4" />
            ) : (
              <Play aria-hidden className="size-4" />
            )}
            {playing ? t("pause") : t("play")}
          </Button>
          <label htmlFor={sliderId} className="sr-only">
            {t("position")}
          </label>
          <input
            id={sliderId}
            type="range"
            min={0}
            max={Math.max(1, end)}
            step={1000}
            value={Math.min(offset, Math.max(1, end))}
            aria-valuetext={t("positionText", { at: clock(offset), end: clock(end) })}
            onChange={(event) => onSeek(Number(event.target.value))}
            className="h-2 flex-1 accent-accent"
          />
          <output className="whitespace-nowrap text-muted-foreground text-sm tabular-nums">
            {t("positionText", { at: clock(offset), end: clock(end) })}
          </output>
        </div>
      )}
    </section>
  );
}
