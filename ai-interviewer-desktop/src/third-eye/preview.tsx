import { Button } from "@hirevion/ui";
import {
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  Room,
  RoomEvent,
  Track,
  type TrackPublication,
} from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { commands } from "../native/commands";
import { ErrorText } from "../screens/shell";
import { videoFrameSource } from "../vision/face-module";
import { PlacementDetector, type Seen } from "./detector";
import {
  type Box,
  type Detection,
  type Framing,
  framing,
  type Part,
  Steady,
  toScreen,
} from "./framing";

/** How often a frame of the phone's picture is checked. */
const TICK_MS = 500;
/** Green after 3 s of green pictures; back after 1 s without one. */
const GREEN_AFTER_MS = 3_000;
const GREEN_LOST_AFTER_MS = 1_000;
/** No picture this long after joining: say so instead of waiting. */
const NO_PICTURE_MS = 20_000;
const COLORS: Record<Part, string> = { ok: "#16a34a", cut: "#d97706", missing: "#d97706" };

/** What the stub's phone "films" (HV_DESKTOP_STUB): a candidate and a laptop, well placed. */
const STUB_PICTURE: Seen = {
  width: 1280,
  height: 720,
  detections: [
    { label: "person", score: 0.9, box: { x: 560, y: 80, width: 380, height: 640 } },
    { label: "laptop", score: 0.8, box: { x: 160, y: 380, width: 380, height: 220 } },
  ] satisfies Detection[],
};

export interface Verdict {
  /** Held green: the candidate and their whole laptop are in the picture. */
  green: boolean;
  /** The latest frame's verdict, or `null` before the first one. */
  framing: Framing | null;
  /** While green, the latest green frame's verdict: what the placement record carries. */
  evidence: Framing | null;
}

const NOTHING: Verdict = { green: false, framing: null, evidence: null };

/** Whether the screen would show anything different (it re-renders only then). */
function same(a: Verdict, b: Verdict): boolean {
  return (
    a.green === b.green &&
    a.framing?.person === b.framing?.person &&
    a.framing?.laptop === b.framing?.laptop &&
    (a.framing === null) === (b.framing === null) &&
    a.evidence === b.evidence
  );
}

type Mode = "loading" | "live" | "stub" | "failed" | "check-failed";

/**
 * The phone's live picture on the desktop (C8-3, product owner, 2026-11-15), with what the
 * on-device detector sees drawn over it. The parent turns the verdict into the green zone.
 */
export function PhonePreview({
  interviewId,
  onVerdict,
}: {
  interviewId: string;
  onVerdict: (verdict: Verdict) => void;
}) {
  const t = useTranslations("thirdEye.check");
  const video = useRef<HTMLVideoElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const [mode, setMode] = useState<Mode>("loading");
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(onVerdict);
  useEffect(() => {
    latest.current = onVerdict;
  });

  // Joins the room with the watch-only token and shows the phone's camera while it films.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` re-joins on "Try again".
  useEffect(() => {
    let room: Room | null = null;
    let cancelled = false;
    let phone = "";
    setMode("loading");
    const isPhoneVideo = (publication: TrackPublication, who: { identity: string }) =>
      publication.kind === Track.Kind.Video && who.identity === phone;
    // A phone that never shows a picture (or stops) is said, not waited on.
    let noPicture = window.setTimeout(() => !cancelled && setMode("failed"), NO_PICTURE_MS);
    const waitForPicture = () => {
      window.clearTimeout(noPicture);
      noPicture = window.setTimeout(() => !cancelled && setMode("failed"), NO_PICTURE_MS);
      setMode("loading");
    };
    const showPicture = () => {
      window.clearTimeout(noPicture);
      setMode("live");
    };
    void (async () => {
      try {
        const access = await commands.thirdEyePreview(interviewId);
        if (cancelled) return;
        if (access === null) {
          window.clearTimeout(noPicture);
          setMode("stub");
          return;
        }
        phone = access.phone_identity;
        const joined = new Room({ adaptiveStream: false, dynacast: false });
        room = joined;
        joined.on(
          RoomEvent.TrackSubscribed,
          (track: RemoteTrack, publication: RemoteTrackPublication, who: RemoteParticipant) => {
            if (!isPhoneVideo(publication, who) || !video.current) return;
            track.attach(video.current);
            if (!publication.isMuted) showPicture();
          },
        );
        // A locked phone or a stopped camera: drop the picture rather than keep its last frame.
        joined.on(RoomEvent.TrackUnsubscribed, (track, publication, who) => {
          if (!isPhoneVideo(publication, who)) return;
          track.detach();
          waitForPicture();
        });
        joined.on(RoomEvent.TrackMuted, (publication, who) => {
          if (isPhoneVideo(publication, who)) waitForPicture();
        });
        joined.on(RoomEvent.TrackUnmuted, (publication, who) => {
          if (isPhoneVideo(publication, who)) showPicture();
        });
        joined.on(RoomEvent.Disconnected, () => {
          if (!cancelled) setMode("failed");
        });
        await joined.connect(access.livekit_url, access.token);
      } catch {
        if (!cancelled) setMode("failed");
      }
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(noPicture);
      void room?.disconnect();
    };
  }, [interviewId, attempt]);

  // Checks a frame twice a second and draws what was seen.
  useEffect(() => {
    if (mode !== "live" && mode !== "stub") return;
    const steady = new Steady(GREEN_AFTER_MS, GREEN_LOST_AFTER_MS);
    const detector = mode === "live" ? new PlacementDetector() : null;
    const frames = video.current ? videoFrameSource(video.current) : null;
    let stopped = false;
    let shown: Verdict = NOTHING;
    let lastGreen: Framing | null = null;
    const timer = window.setInterval(async () => {
      let seen: Seen | null = STUB_PICTURE;
      if (detector) {
        seen = frames ? await detector.detect(frames) : null;
        if (detector.failed && !stopped) {
          setMode("check-failed");
          return;
        }
      }
      if (stopped || !seen) return;
      const verdict = framing(seen.detections, seen.width, seen.height);
      if (verdict.green) lastGreen = verdict;
      const green = steady.update(verdict.green, performance.now());
      draw(overlay.current, verdict, seen);
      const next: Verdict = { green, framing: verdict, evidence: green ? lastGreen : null };
      if (!same(shown, next)) {
        shown = next;
        latest.current(next);
      }
    }, TICK_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      detector?.close();
      clear(overlay.current);
      latest.current(NOTHING);
    };
  }, [mode]);

  const failed = mode === "failed" || mode === "check-failed";
  return (
    <div className="grid gap-2">
      <div className="relative h-[40vh] min-h-48 w-full overflow-hidden rounded-md bg-black">
        <video
          ref={video}
          autoPlay
          muted
          playsInline
          aria-label={t("videoLabel")}
          className="h-full w-full object-contain"
          hidden={mode === "stub"}
        />
        {mode === "stub" || mode === "loading" ? (
          <p className="absolute inset-0 grid place-items-center text-sm text-white/80">
            {mode === "stub" ? t("stub") : t("loading")}
          </p>
        ) : null}
        <canvas
          ref={overlay}
          aria-hidden
          className="pointer-events-none absolute inset-0 size-full"
        />
      </div>
      {failed ? (
        <div className="flex flex-wrap items-center gap-2">
          <ErrorText>{mode === "failed" ? t("failed") : t("checkFailed")}</ErrorText>
          <Button variant="secondary" size="sm" onClick={() => setAttempt((count) => count + 1)}>
            {t("retry")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function clear(canvas: HTMLCanvasElement | null) {
  canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
}

function draw(canvas: HTMLCanvasElement | null, verdict: Framing, seen: Seen) {
  if (!canvas) return;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  const outline = (box: Box | null, part: Part) => {
    if (!box) return;
    const placed = toScreen(box, seen, { width, height });
    context.strokeStyle = COLORS[part];
    context.lineWidth = 3;
    context.strokeRect(placed.x, placed.y, placed.width, placed.height);
  };
  outline(verdict.personBox, verdict.person);
  outline(verdict.laptopBox, verdict.laptop);
}
