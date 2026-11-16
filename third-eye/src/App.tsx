import { kbps, summarizeConnection, type VideoSample, videoSample } from "@hirevion/rtc-stats";
import type { LocalVideoTrack } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";
import { type JoinResponse, PairingError, redeem, rejoin, roomUrl, stillValid } from "./api";
import { captureOptions, type Facing, needsTurning, nextFacing } from "./camera";
import { cameraHelp, detectBrowser } from "./guidance";
import { browserDeps } from "./livekit";
import { EyeSession, type EyeState } from "./session";
import { readToken, recallDevice, rememberDevice, wantsAutoStart } from "./token";

type Phase = "pairing" | "ready" | "camera" | "streaming" | "denied" | "error";

const STATS_INTERVAL_MS = 2_000;
const STATE_TEXT: Record<EyeState, string> = {
  idle: "Not started",
  starting: "Starting the camera…",
  live: "Live: the interview can see this camera",
  paused: "Paused: keep this page open and the screen on",
  reconnecting: "Reconnecting…",
  failed: "Stopped",
  ended: "Ended: this pairing was cancelled",
};

// Read once, before the fragment is removed from the address bar (and the history).
const hash = window.location.hash;
const pairingToken = readToken(hash);
const autoStart = wantsAutoStart(hash);
const pageOpened = performance.now();
if (hash) {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

function storage(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
}

export function App() {
  const browser = detectBrowser(navigator.userAgent);
  const preview = useRef<HTMLVideoElement>(null);
  const session = useRef<EyeSession | null>(null);
  const camera = useRef<LocalVideoTrack | null>(null);
  const started = useRef(false);
  const [phase, setPhase] = useState<Phase>("pairing");
  const [joined, setJoined] = useState<JoinResponse | null>(null);
  const [state, setState] = useState<EyeState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [pairedIn, setPairedIn] = useState<number | null>(null);
  const [video, setVideo] = useState<string | null>(null);
  const [facing, setFacing] = useState<Facing>("environment");
  const [switching, setSwitching] = useState(false);
  // The picture's shape follows how the phone stands; an upright phone films a tall picture.
  const [upright, setUpright] = useState(false);

  // Spend the token at once: it lives two minutes. A reload rejoins with the device secret.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const device = recallDevice(storage());
    const join = pairingToken
      ? redeem(pairingToken, navigator.userAgent)
      : device
        ? rejoin(device)
        : Promise.reject(
            new PairingError(
              "no-token",
              "This link has no pairing code. Scan the QR code on the interview computer.",
              true,
            ),
          );
    join
      .then((answer) => {
        rememberDevice(storage(), answer.device_token);
        setJoined(answer);
        setPhase("ready");
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
        setPhase("error");
      });
  }, []);

  const start = useCallback(async () => {
    if (!joined) return;
    setPhase("camera");
    setError(null);
    const credentials = async () => {
      const device = recallDevice(storage());
      if (!device) {
        throw new PairingError("no-device", "Scan the QR code again.", true);
      }
      const answer = await rejoin(device);
      return {
        url: roomUrl(answer.livekit_url, window.location.host),
        token: answer.participant_token,
      };
    };
    const deps = browserDeps(credentials, (track) => {
      camera.current = track;
      if (preview.current) track.attach(preview.current);
    });
    try {
      // The redeem's token lives 10 minutes; a candidate who took longer to place the phone
      // gets a fresh one with the device secret.
      const first = stillValid(joined.expires_at)
        ? {
            url: roomUrl(joined.livekit_url, window.location.host),
            token: joined.participant_token,
          }
        : await credentials();
      await session.current?.stop();
      setUpright(false); // a new stream reports its own shape
      const next = new EyeSession(deps, first, setState);
      session.current = next;
      await next.start();
      setPairedIn((performance.now() - pageOpened) / 1000);
      setPhase("streaming");
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "NotAllowedError") {
        setPhase("denied");
        return;
      }
      setError(caught instanceof Error ? caught.message : String(caught));
      setPhase("error");
    }
  }, [joined]);

  useEffect(() => {
    if (phase === "ready" && autoStart) void start();
  }, [phase, start]);

  // A locked phone or another app: unpublish now (the server notices within seconds).
  useEffect(() => {
    const changed = () => {
      const current = session.current;
      if (!current) return;
      void (document.visibilityState === "hidden" ? current.hidden() : current.visible());
    };
    const leaving = () => void session.current?.hidden();
    document.addEventListener("visibilitychange", changed);
    window.addEventListener("pagehide", leaving);
    return () => {
      document.removeEventListener("visibilitychange", changed);
      window.removeEventListener("pagehide", leaving);
    };
  }, []);

  useEffect(() => {
    if (phase !== "streaming") return;
    let previous: VideoSample | null = null;
    const timer = window.setInterval(async () => {
      const report = await camera.current?.getRTCStatsReport();
      if (!report) return;
      const pair = summarizeConnection(report);
      const sample = videoSample(report);
      const rate = previous && sample ? kbps(previous, sample) : null;
      previous = sample;
      setVideo(
        sample
          ? `${sample.width ?? "?"}×${sample.height ?? "?"}, ${sample.fps ?? "?"} fps, ${rate ?? "?"} kbps${pair ? `, ${pair.protocol.toUpperCase()}` : ""}`
          : null,
      );
    }, STATS_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [phase]);

  // Rear or front camera (owner, 2026-11-15): the published track stays, only its camera changes.
  async function switchCamera() {
    const track = camera.current;
    if (!track || switching) return;
    const next = nextFacing(facing);
    setSwitching(true);
    try {
      await track.restartTrack(captureOptions(next));
      setFacing(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSwitching(false);
    }
  }

  return (
    <main className="eye">
      <h1>Third Eye</h1>
      {joined && (
        <p className="context">
          {joined.interview.company} · {joined.interview.job_title}
        </p>
      )}
      {phase === "pairing" && <p role="status">Pairing with the interview…</p>}
      {phase === "error" && <p role="alert">{error}</p>}
      {phase === "error" && joined && (
        <button type="button" onClick={() => void start()}>
          Try again
        </button>
      )}

      {(phase === "ready" || phase === "camera" || phase === "denied") && joined && (
        <section aria-labelledby="placement">
          <h2 id="placement">Place this phone</h2>
          <ol className="steps">
            <li>Stand this phone sideways (landscape), not upright.</li>
            <li>
              On your left or right side, about {joined.placement.distance_m} m away and a little
              behind you, at about head height.
            </li>
            <li>
              Point the camera so it sees all of you and your whole laptop, keyboard included. The
              interview computer shows you what it sees.
            </li>
            <li>Pick a well-lit spot, without a bright window behind you.</li>
            <li>Plug in the charger and stand the phone so it doesn't move.</li>
            <li>Keep this page open and the screen on until the interview ends.</li>
          </ol>
          <figure className="placement" aria-hidden="true">
            <div className="desk">Screen</div>
            <div className="you">You</div>
            <div className="phone">Phone</div>
          </figure>
        </section>
      )}

      {phase === "ready" && (
        <>
          {cameraHelp(browser, "prompt").map((line) => (
            <p key={line}>{line}</p>
          ))}
          <button type="button" onClick={() => void start()}>
            Start camera
          </button>
        </>
      )}
      {phase === "camera" && <p role="status">Starting the camera…</p>}
      {phase === "denied" && (
        <section role="alert" aria-labelledby="denied">
          <h2 id="denied">The camera is blocked</h2>
          {cameraHelp(browser, "denied").map((line) => (
            <p key={line}>{line}</p>
          ))}
          <button type="button" onClick={() => void start()}>
            Try again
          </button>
        </section>
      )}

      {phase === "streaming" && upright && (
        <p role="alert" className="turn">
          Turn this phone sideways (landscape). Standing upright, it can't fit you and your whole
          laptop in the picture.
        </p>
      )}
      <video
        ref={preview}
        autoPlay
        muted
        playsInline
        hidden={phase !== "streaming"}
        // The first size may come with the metadata and no `resize` (some WebKit versions).
        onLoadedMetadata={(event) =>
          setUpright(needsTurning(event.currentTarget.videoWidth, event.currentTarget.videoHeight))
        }
        onResize={(event) =>
          setUpright(needsTurning(event.currentTarget.videoWidth, event.currentTarget.videoHeight))
        }
      />
      {phase === "streaming" && (
        <button type="button" disabled={switching} onClick={() => void switchCamera()}>
          {facing === "environment" ? "Use the front camera" : "Use the back camera"}
        </button>
      )}
      {phase === "streaming" && error && <p role="alert">{error}</p>}
      {phase === "streaming" && (
        <dl>
          <dt>Status</dt>
          <dd role="status" data-state={state}>
            {STATE_TEXT[state]}
          </dd>
          {pairedIn !== null && (
            <>
              <dt>Paired in</dt>
              <dd data-testid="paired-in">{pairedIn.toFixed(1)} s</dd>
            </>
          )}
          {video && (
            <>
              <dt>Video</dt>
              <dd>{video}</dd>
            </>
          )}
        </dl>
      )}
    </main>
  );
}
