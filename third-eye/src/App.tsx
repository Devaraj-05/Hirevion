import { kbps, summarizeConnection, type VideoSample, videoSample } from "@hirevion/rtc-stats";
import type { LocalVideoTrack } from "livekit-client";
import {
  BatteryCharging,
  Camera,
  Lightbulb,
  MonitorSmartphone,
  RotateCw,
  ScanEye,
  SwitchCamera,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { type JoinResponse, PairingError, redeem, rejoin, roomUrl, stillValid } from "./api";
import { captureOptions, type Facing, needsTurning, nextFacing } from "./camera";
import { cameraHelp, detectBrowser } from "./guidance";
import { browserDeps } from "./livekit";
import { type LockResult, lockLandscape, turnAdvice } from "./orientation";
import { EyeSession, type EyeState } from "./session";
import { readToken, recallDevice, rememberDevice, wantsAutoStart } from "./token";

type Phase = "pairing" | "ready" | "camera" | "streaming" | "denied" | "error";

const STATS_INTERVAL_MS = 2_000;
const STATE_TEXT: Record<EyeState, string> = {
  idle: "Not started",
  starting: "Starting the camera…",
  live: "Live. The interview can see this camera.",
  paused: "Paused. Unlock the phone and keep this page open.",
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
  // Whether the page could lock itself to landscape (it can only after a tap).
  const [lock, setLock] = useState<LockResult | null>(null);

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
    // Before the camera opens, so it films landscape from the start, even with rotation locked.
    // Only on a tap: the browser refuses full screen otherwise.
    if (!autoStart) setLock(await lockLandscape());
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

  // Locks the page to landscape, then restarts the camera so it films the new orientation.
  async function turnToLandscape() {
    const result = await lockLandscape();
    setLock(result);
    if (result !== "locked") return;
    try {
      await camera.current?.restartTrack(captureOptions(facing));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  const advice = turnAdvice(lock);
  const placing = (phase === "ready" || phase === "camera" || phase === "denied") && joined;
  return (
    <main className="eye">
      <header className="brand">
        <span className="mark">
          <ScanEye size={18} aria-hidden />
          Hirevion
        </span>
        <span>Second camera</span>
      </header>

      {phase === "pairing" && (
        <div className="waiting" role="status">
          <span className="spinner" aria-hidden />
          Connecting to your interview…
        </div>
      )}

      {phase === "error" && (
        <section className="message danger" role="alert">
          <strong>This phone couldn't connect</strong>
          {error}
          {joined && (
            <button type="button" className="button" onClick={() => void start()}>
              Try again
            </button>
          )}
        </section>
      )}

      {placing && (
        <>
          <div className="hero">
            <h1>Set up your second camera</h1>
            <p className="context">
              {joined.interview.company} · {joined.interview.job_title}
            </p>
          </div>
          <section className="card" aria-labelledby="placement">
            <h2 id="placement">Place this phone</h2>
            <figure className="placement" aria-hidden="true">
              <div className="view" />
              <div className="desk" />
              <div className="laptop">Laptop</div>
              <div className="you">You</div>
              <div className="phone">Phone</div>
              <figcaption>Seen from above</figcaption>
            </figure>
            <ol className="steps">
              <li>
                <span className="icon">
                  <MonitorSmartphone size={18} aria-hidden />
                </span>
                <span>
                  On your left or right, about {joined.placement.distance_m} m away and a little
                  behind you.
                </span>
              </li>
              <li>
                <span className="icon">
                  <RotateCw size={18} aria-hidden />
                </span>
                <span>Sideways (landscape), standing at about head height.</span>
              </li>
              <li>
                <span className="icon">
                  <ScanEye size={18} aria-hidden />
                </span>
                <span>
                  Seeing all of you and your whole laptop, keyboard included. The interview computer
                  shows you the picture.
                </span>
              </li>
              <li>
                <span className="icon">
                  <Lightbulb size={18} aria-hidden />
                </span>
                <span>In a well-lit spot, with no bright window behind you.</span>
              </li>
              <li>
                <span className="icon">
                  <BatteryCharging size={18} aria-hidden />
                </span>
                <span>Plugged in and steady, with this page open until the interview ends.</span>
              </li>
            </ol>
          </section>
        </>
      )}

      {phase === "denied" && (
        <section className="message danger" role="alert" aria-labelledby="denied">
          <strong id="denied">The camera is blocked</strong>
          {cameraHelp(browser, "denied").map((line) => (
            <span key={line}>{line}</span>
          ))}
          <button type="button" className="button" onClick={() => void start()}>
            Try again
          </button>
        </section>
      )}

      {phase === "ready" &&
        cameraHelp(browser, "prompt").map((line) => (
          <p key={line} className="note">
            {line}
          </p>
        ))}
      {/* Only the button stays under the thumb; the advice above scrolls with the page. */}
      {(phase === "ready" || phase === "camera") && (
        <div className="action">
          <button
            type="button"
            className="button"
            disabled={phase === "camera"}
            onClick={() => void start()}
          >
            <Camera size={18} aria-hidden />
            {phase === "camera" ? "Starting the camera…" : "Start camera"}
          </button>
        </div>
      )}

      {phase === "streaming" && (
        <div className="hero">
          <h1>{state === "live" ? "You're on camera" : "Second camera"}</h1>
          <p>Leave this phone where it is, with this page open, until the interview ends.</p>
        </div>
      )}

      {phase === "streaming" && upright && (
        <section className="message warning">
          <strong role="alert">
            Turn this phone sideways (landscape). Standing upright, it can't fit you and your whole
            laptop in the picture.
          </strong>
          {advice.button && (
            <button type="button" className="button" onClick={() => void turnToLandscape()}>
              <RotateCw size={18} aria-hidden />
              Turn to landscape
            </button>
          )}
          {advice.rotationHint && (
            <span>
              If the picture stays upright with the phone sideways, switch rotation lock off
              (auto-rotate on) in the phone's quick settings.
            </span>
          )}
        </section>
      )}

      <div className="preview" hidden={phase !== "streaming"}>
        <video
          ref={preview}
          autoPlay
          muted
          playsInline
          hidden={phase !== "streaming"}
          // The first size may come with the metadata and no `resize` (some WebKit versions).
          onLoadedMetadata={(event) =>
            setUpright(
              needsTurning(event.currentTarget.videoWidth, event.currentTarget.videoHeight),
            )
          }
          onResize={(event) =>
            setUpright(
              needsTurning(event.currentTarget.videoWidth, event.currentTarget.videoHeight),
            )
          }
        />
      </div>

      {phase === "streaming" && (
        <section className="card">
          <p className="status" role="status" data-state={state}>
            {STATE_TEXT[state]}
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={switching}
            onClick={() => void switchCamera()}
          >
            <SwitchCamera size={18} aria-hidden />
            {facing === "environment" ? "Use the front camera" : "Use the back camera"}
          </button>
          {error && (
            <p className="message danger" role="alert">
              {error}
            </p>
          )}
          <details>
            <summary>Connection details</summary>
            <dl>
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
          </details>
        </section>
      )}
    </main>
  );
}
