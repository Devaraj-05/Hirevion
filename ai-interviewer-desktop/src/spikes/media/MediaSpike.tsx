import { useEffect, useRef, useState } from "react";
import { reportSpike } from "../report";
import type { Delegate } from "./face-worker";
import { FaceLoop, type FaceReport } from "./faces";
import { CameraRecorder, type RecorderReport } from "./recorder";

export type FaceMode = "off" | "gpu" | "cpu";

const OPTIONS = {
  segmentSeconds: 10,
  frameRate: 15,
  videoBitrate: 1_000_000,
  audioBitrate: 32_000,
};

interface Running {
  stream: MediaStream;
  recorder: CameraRecorder;
  faces: FaceLoop | null;
  startedAt: number;
  cameraOpenMs: number;
}

/** Asks for the location, which the app's permission policy must deny without a prompt. */
function probeGeolocation(): Promise<string> {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      () => resolve("granted"),
      (error) => resolve(error.code === error.PERMISSION_DENIED ? "denied" : `error ${error.code}`),
      { timeout: 3_000 },
    );
  });
}

/**
 * SP-00d media spike: camera + microphone into 10-second MP4 segments (WebCodecs +
 * Mediabunny, saved by Rust) with optional MediaPipe face detection.
 * `#/media?auto=<seconds>&faces=gpu|cpu|off` runs unattended and reports the numbers.
 */
export function MediaSpike({
  autoSeconds,
  faceMode,
}: {
  autoSeconds: number | null;
  faceMode: FaceMode;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const running = useRef<Running | null>(null);
  // StrictMode runs effects twice in development; the unattended run must start once.
  const autoStarted = useRef(false);
  const [status, setStatus] = useState("idle");
  const [fps, setFps] = useState(0);
  const [result, setResult] = useState<string | null>(null);

  const start = async (mode: FaceMode): Promise<void> => {
    setStatus("opening camera");
    const opening = performance.now();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 15, max: 15 } },
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const cameraOpenMs = performance.now() - opening;
    if (video.current) {
      video.current.srcObject = stream;
      await video.current.play();
    }
    const recorder = await CameraRecorder.start(stream, OPTIONS);
    let faces: FaceLoop | null = null;
    if (mode !== "off" && video.current) {
      const delegate: Delegate = mode === "gpu" ? "GPU" : "CPU";
      faces = new FaceLoop(video.current, delegate, OPTIONS.frameRate);
      await faces.start();
    }
    running.current = { stream, recorder, faces, startedAt: performance.now(), cameraOpenMs };
    setStatus(`recording (faces: ${mode})`);
  };

  const stop = async (): Promise<Record<string, unknown> | null> => {
    const current = running.current;
    if (!current) {
      return null;
    }
    running.current = null;
    setStatus("stopping");
    const faces: FaceReport | null = current.faces?.stop() ?? null;
    const recording: RecorderReport = await current.recorder.stop();
    const settings = current.stream.getVideoTracks()[0]?.getSettings() ?? {};
    for (const track of current.stream.getTracks()) {
      track.stop();
    }
    const summary = {
      seconds: (performance.now() - current.startedAt) / 1_000,
      cameraOpenMs: current.cameraOpenMs,
      camera: { width: settings.width, height: settings.height, frameRate: settings.frameRate },
      recording,
      faces,
    };
    setStatus("stopped");
    setResult(
      `${recording.segments.length} segments, ${recording.framesEncoded} frames encoded, ` +
        `${recording.framesDropped} dropped; faces ${faces ? `${faces.fps.toFixed(1)} fps` : "off"}`,
    );
    return summary;
  };

  useEffect(() => {
    const timer = window.setInterval(() => setFps(running.current?.faces?.fps ?? 0), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  // Runs once per unattended run; `start` and `stop` are plain functions recreated each render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see the comment above.
  useEffect(() => {
    if (autoSeconds === null || autoStarted.current) {
      return;
    }
    autoStarted.current = true;
    const run = async () => {
      const geolocation = await probeGeolocation();
      const began = performance.now();
      let summary: Record<string, unknown> | null = null;
      let error: string | null = null;
      try {
        await start(faceMode);
        await new Promise((resolve) => window.setTimeout(resolve, autoSeconds * 1_000));
        summary = await stop();
      } catch (caught) {
        error = caught instanceof Error ? caught.message : String(caught);
      }
      await reportSpike("media", {
        faceMode,
        geolocation,
        // No prompt was answered, so reaching here without an error means the grant was automatic.
        cameraGrantedWithoutPrompt: error === null,
        wallSeconds: (performance.now() - began) / 1_000,
        error,
        ...summary,
      });
    };
    void run();
  }, [autoSeconds, faceMode]);

  return (
    <section aria-labelledby="media-title">
      <h2 id="media-title">Media spike</h2>
      <p role="status">
        {status}
        {fps > 0 && `, face detection ${fps.toFixed(1)} fps`}
      </p>
      <div>
        <button type="button" onClick={() => void start("off")}>
          Record
        </button>
        <button type="button" onClick={() => void start("gpu")}>
          Record + faces (GPU)
        </button>
        <button type="button" onClick={() => void start("cpu")}>
          Record + faces (CPU)
        </button>
        <button type="button" onClick={() => void stop()}>
          Stop
        </button>
      </div>
      {result && <p>{result}</p>}
      <video ref={video} muted playsInline />
    </section>
  );
}
