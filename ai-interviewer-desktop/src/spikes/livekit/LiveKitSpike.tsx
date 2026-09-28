import { kbps, summarizeConnection, type VideoSample, videoSample } from "@hirevion/rtc-stats";
import {
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { reportSpike, spikeConfig } from "../report";

const STATS_INTERVAL_MS = 2_000;
const DEFAULT_URL = "wss://livekit.hirevion.localhost";

interface Sample {
  atMs: number;
  protocol: string | null;
  localType: string | null;
  remoteType: string | null;
  rttMs: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  kbps: number | null;
  packetsLost: number | null;
}

/**
 * SP-00d LiveKit spike: joins a room and shows the phone's third-eye camera with its
 * connection statistics. `#/livekit?auto=<seconds>` joins with the token from HV_SPIKE_TOKEN,
 * records samples for that long and reports them.
 */
export function LiveKitSpike({ autoSeconds }: { autoSeconds: number | null }) {
  const video = useRef<HTMLVideoElement>(null);
  const room = useRef<Room | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // StrictMode runs effects twice in development; the unattended run must start once.
  const autoStarted = useRef(false);
  const [url, setUrl] = useState(DEFAULT_URL);
  const [token, setToken] = useState("");
  const [state, setState] = useState("not connected");
  const [firstFrameMs, setFirstFrameMs] = useState<number | null>(null);
  const [latest, setLatest] = useState<Sample | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () => () => {
      window.clearInterval(timer.current);
      void room.current?.disconnect();
    },
    [],
  );

  const join = async (joinUrl: string, joinToken: string, seconds: number | null) => {
    setError(null);
    const samples: Sample[] = [];
    const began = performance.now();
    let joinedMs: number | null = null;
    let frameMs: number | null = null;
    let reconnects = 0;
    let joinError: string | null = null;
    try {
      const next = new Room({ adaptiveStream: false, dynacast: false });
      room.current = next;
      next.on(RoomEvent.ConnectionStateChanged, (connection) => setState(connection));
      next.on(RoomEvent.Reconnected, () => {
        reconnects += 1;
      });
      next.on(
        RoomEvent.TrackSubscribed,
        (track: RemoteTrack, _publication: RemoteTrackPublication, _who: RemoteParticipant) => {
          if (track.kind !== Track.Kind.Video || !video.current) {
            return;
          }
          const element = video.current;
          track.attach(element);
          element.requestVideoFrameCallback(() => {
            frameMs = performance.now() - began;
            setFirstFrameMs(frameMs);
          });
          let previous: VideoSample | null = null;
          window.clearInterval(timer.current);
          timer.current = window.setInterval(async () => {
            const report = await track.getRTCStatsReport();
            if (!report) {
              return;
            }
            const pair = summarizeConnection(report);
            const current = videoSample(report);
            const sample: Sample = {
              atMs: Math.round(performance.now() - began),
              protocol: pair?.protocol ?? null,
              localType: pair?.localType ?? null,
              remoteType: pair?.remoteType ?? null,
              rttMs: pair?.rttMs ?? null,
              fps: current?.fps ?? null,
              width: current?.width ?? null,
              height: current?.height ?? null,
              kbps: previous && current ? kbps(previous, current) : null,
              packetsLost: current?.packetsLost ?? null,
            };
            previous = current;
            samples.push(sample);
            setLatest(sample);
          }, STATS_INTERVAL_MS);
        },
      );
      await next.connect(joinUrl, joinToken);
      joinedMs = performance.now() - began;
    } catch (caught) {
      joinError = caught instanceof Error ? caught.message : String(caught);
      setError(joinError);
    }
    if (seconds !== null) {
      window.setTimeout(async () => {
        window.clearInterval(timer.current);
        await room.current?.disconnect();
        await reportSpike("livekit", {
          url: joinUrl,
          joinMs: joinedMs,
          firstFrameMs: frameMs,
          reconnects,
          error: joinError,
          samples,
        });
      }, seconds * 1_000);
    }
  };

  // Runs once per unattended run; `join` is a plain function recreated each render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see the comment above.
  useEffect(() => {
    if (autoSeconds === null || autoStarted.current) {
      return;
    }
    autoStarted.current = true;
    void spikeConfig().then((config) => {
      if (config.livekitToken) {
        void join(config.livekitUrl, config.livekitToken, autoSeconds);
      } else {
        setError("HV_SPIKE_TOKEN is not set; see the runbook.");
      }
    });
  }, [autoSeconds]);

  return (
    <section aria-labelledby="livekit-title">
      <h2 id="livekit-title">LiveKit spike</h2>
      <p>
        Paste a token from <code>uv run hv lk-token --room spike --identity desktop --copy</code>,
        then open the phone link from <code>uv run hv eye-tunnel</code>.
      </p>
      <label>
        LiveKit URL <input value={url} onChange={(event) => setUrl(event.target.value)} />
      </label>
      <label>
        Token <input value={token} onChange={(event) => setToken(event.target.value)} />
      </label>
      <button type="button" disabled={!token} onClick={() => void join(url, token, null)}>
        Join
      </button>
      <p role="status">
        {state}
        {firstFrameMs !== null && `, first phone frame after ${Math.round(firstFrameMs)} ms`}
      </p>
      {error && <p role="alert">{error}</p>}
      <video ref={video} autoPlay muted playsInline />
      {latest && (
        <p>
          {latest.protocol ?? "?"} {latest.localType ?? "?"} to {latest.remoteType ?? "?"}, RTT{" "}
          {latest.rttMs ?? "?"} ms; {latest.width ?? "?"}x{latest.height ?? "?"} at{" "}
          {latest.fps ?? "?"} fps, {latest.kbps ?? "?"} kbps, {latest.packetsLost ?? 0} packets lost
        </p>
      )}
    </section>
  );
}
