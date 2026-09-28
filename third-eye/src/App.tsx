import { kbps, summarizeConnection, type VideoSample, videoSample } from "@hirevion/rtc-stats";
import { LocalVideoTrack, Room, RoomEvent, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { readToken } from "./token";

type Phase = "ready" | "starting" | "live" | "failed";

interface Timings {
  cameraMs: number;
  connectMs: number;
  publishMs: number;
}

interface LiveStats {
  network: string;
  video: string;
}

const STATS_INTERVAL_MS = 2_000;

export function App() {
  const token = readToken(window.location.hash);
  const preview = useRef<HTMLVideoElement>(null);
  const room = useRef<Room | null>(null);
  const statsTimer = useRef<number | undefined>(undefined);
  const [phase, setPhase] = useState<Phase>("ready");
  const [connection, setConnection] = useState("not connected");
  const [timings, setTimings] = useState<Timings | null>(null);
  const [live, setLive] = useState<LiveStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () => () => {
      window.clearInterval(statsTimer.current);
      void room.current?.disconnect();
    },
    [],
  );

  if (!token) {
    return (
      <main className="eye">
        <h1>Third Eye</h1>
        <p>This link has no pairing code. Scan the QR code on the interview computer again.</p>
      </main>
    );
  }

  const watchStats = (track: LocalVideoTrack) => {
    let previous: VideoSample | null = null;
    window.clearInterval(statsTimer.current);
    statsTimer.current = window.setInterval(async () => {
      const report = await track.getRTCStatsReport();
      if (!report) {
        return;
      }
      const pair = summarizeConnection(report);
      const sample = videoSample(report);
      const rate = previous && sample ? kbps(previous, sample) : null;
      previous = sample;
      setLive({
        network: pair
          ? `${pair.protocol.toUpperCase()}, ${pair.localType} to ${pair.remoteType}, RTT ${pair.rttMs ?? "?"} ms`
          : "negotiating",
        video: sample
          ? `${sample.width ?? "?"}x${sample.height ?? "?"} at ${sample.fps ?? "?"} fps, ${rate ?? "?"} kbps`
          : "no video yet",
      });
    }, STATS_INTERVAL_MS);
  };

  const start = async () => {
    setPhase("starting");
    setError(null);
    await room.current?.disconnect();
    try {
      const began = performance.now();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 15, max: 15 },
        },
      });
      const camera = stream.getVideoTracks()[0];
      if (!camera) {
        throw new Error("The camera returned no video.");
      }
      if (preview.current) {
        preview.current.srcObject = stream;
      }
      const cameraReady = performance.now();

      const next = new Room({ adaptiveStream: false, dynacast: false });
      room.current = next;
      next.on(RoomEvent.ConnectionStateChanged, (state) => setConnection(state));
      next.on(RoomEvent.Reconnecting, () => setConnection("reconnecting"));
      next.on(RoomEvent.Reconnected, () => setConnection("reconnected"));
      // Caddy routes /rtc on this same origin to LiveKit, so no other host is involved.
      await next.connect(`wss://${window.location.host}`, token);
      const connected = performance.now();

      const track = new LocalVideoTrack(camera);
      await next.localParticipant.publishTrack(track, {
        source: Track.Source.Camera,
        simulcast: false,
        videoEncoding: { maxBitrate: 1_200_000, maxFramerate: 15 },
      });
      const published = performance.now();

      setTimings({
        cameraMs: cameraReady - began,
        connectMs: connected - cameraReady,
        publishMs: published - connected,
      });
      setPhase("live");
      void holdWakeLock();
      watchStats(track);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setPhase("failed");
    }
  };

  return (
    <main className="eye">
      <h1>Third Eye</h1>
      <p>
        Place this phone about 1.5 m behind and to the side of you, so it sees you, your desk and
        your screen. Keep it plugged in and leave this page open.
      </p>
      <video ref={preview} autoPlay muted playsInline />
      {phase === "ready" && (
        <button type="button" onClick={() => void start()}>
          Start camera
        </button>
      )}
      {phase === "starting" && <p role="status">Starting the camera...</p>}
      {phase === "failed" && (
        <>
          <p role="alert">{error}</p>
          <button type="button" onClick={() => void start()}>
            Try again
          </button>
        </>
      )}
      <dl>
        <dt>Connection</dt>
        <dd>{connection}</dd>
        {timings && (
          <>
            <dt>Start-up</dt>
            <dd>
              camera {Math.round(timings.cameraMs)} ms, connect {Math.round(timings.connectMs)} ms,
              publish {Math.round(timings.publishMs)} ms
            </dd>
          </>
        )}
        {live && (
          <>
            <dt>Network</dt>
            <dd>{live.network}</dd>
            <dt>Video</dt>
            <dd>{live.video}</dd>
          </>
        )}
      </dl>
    </main>
  );
}

/** Keeps the phone's screen on while the camera runs (Safari 16.4+, Chrome). */
async function holdWakeLock(): Promise<void> {
  if (!("wakeLock" in navigator)) {
    return;
  }
  const request = () => navigator.wakeLock.request("screen").catch(() => undefined);
  await request();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      void request();
    }
  });
}
