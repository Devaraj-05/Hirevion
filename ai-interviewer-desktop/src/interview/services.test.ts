import { describe, expect, it, vi } from "vitest";
import type { ServicesStarted } from "../native/commands";
import type { MediaRecording } from "../recording/recorder";
import { DEFAULT_VISION_CONFIG } from "../vision/config";
import type { CameraEvent } from "../vision/types";
import {
  type FaceStartOptions,
  InterviewServices,
  type LocalTracks,
  liveLabel,
  type ServicesDeps,
  serverIso,
} from "./services";

// The tests run in Node, which has no MediaStream.
vi.stubGlobal(
  "MediaStream",
  class {
    constructor(readonly tracks: MediaStreamTrack[] = []) {}
    getTracks() {
      return this.tracks;
    }
  },
);

const EVENTS = { trackRefused: "hv:track-refused", stopMedia: "hv:stop-media" };

function track(kind: "camera" | "mic", state: "live" | "ended" = "live") {
  return {
    kind,
    label: kind === "camera" ? "Integrated Camera" : "Array Microphone",
    readyState: state,
    addEventListener: vi.fn(),
    stop: vi.fn(),
  } as unknown as MediaStreamTrack & { stop: ReturnType<typeof vi.fn> };
}

function tracks(overrides: Partial<LocalTracks> = {}): LocalTracks {
  return { camera: track("camera"), mic: track("mic"), owned: false, ...overrides };
}

const ALL_UP: ServicesStarted = {
  proctoring: true,
  monitoring: true,
  recording: true,
  screen: true,
  policy: { thresholds: { FACE_ABSENT: { warn_after_ms: 1000 } }, accommodations: [] },
  problems: [],
};

function event(): CameraEvent {
  return {
    event: "FACE_ABSENT",
    source: "camera",
    started_at: "2026-10-12T05:01:02.120Z",
    duration_ms: 5000,
    confidence: 1,
    evidence: [],
    details: { phase: "ended", level: "warning", frames: 10 },
  };
}

function harness(started: ServicesStarted | ServicesStarted[] = ALL_UP) {
  const log: string[] = [];
  const answers = Array.isArray(started) ? [...started] : [started];
  const recording = {
    mode: "media-recorder",
    tracks: ["camera", "mic"],
    setServerOffset: vi.fn(),
    stopTrack: vi.fn(async () => null),
    stop: vi.fn(async () => {
      log.push("recording.stop");
      return [];
    }),
  } as unknown as MediaRecording;
  let faceOptions: FaceStartOptions | null = null;
  const handlers = new Map<string, (payload: unknown) => void>();
  const scheduled: (() => void)[] = [];
  const enqueue = vi.fn(async () => {
    log.push("enqueue");
  });
  const deps: ServicesDeps = {
    servicesStart: vi.fn(async () => {
      log.push("services.start");
      return answers.length > 1
        ? (answers.shift() as ServicesStarted)
        : (answers[0] as ServicesStarted);
    }),
    servicesStop: vi.fn(async () => {
      log.push("services.stop");
    }),
    setDevices: vi.fn(async () => undefined),
    enqueue,
    clockOffsetMs: vi.fn(async () => 1500),
    startRecording: vi.fn(async () => recording),
    startFace: vi.fn(async (_camera, options) => {
      faceOptions = options;
      return {
        stop: () => {
          log.push("face.stop");
          // Stopping ends the open episodes: one last event.
          options.onEvent(event());
        },
      };
    }),
    visionConfig: vi.fn(() => DEFAULT_VISION_CONFIG),
    listen: vi.fn(async (name, handler) => {
      handlers.set(name, handler);
      return () => handlers.delete(name);
    }),
    schedule: vi.fn((run) => {
      scheduled.push(run);
      return () => undefined;
    }),
  };
  const problems: string[] = [];
  const ready = vi.fn();
  const services = new InterviewServices("iv-1", deps, {
    events: EVENTS,
    onProblem: (part) => problems.push(part),
    onReady: ready,
  });
  return {
    services,
    deps,
    recording,
    log,
    handlers,
    scheduled,
    problems,
    ready,
    enqueue,
    faceOptions: () => faceOptions,
  };
}

describe("the webview's part of the interview services", () => {
  it("starts recording and the face module once Rust says they can", async () => {
    const h = harness();
    const local = tracks();

    await h.services.start(async () => local);

    expect(h.deps.servicesStart).toHaveBeenCalledWith("iv-1");
    const [stream] = vi.mocked(h.deps.startRecording).mock.calls[0] ?? [];
    expect(stream?.getTracks()).toEqual([local.camera, local.mic]);
    expect(h.deps.startFace).toHaveBeenCalledOnce();
    expect(h.deps.visionConfig).toHaveBeenCalledWith(ALL_UP.policy);
    expect(h.deps.setDevices).toHaveBeenCalledWith("Integrated Camera", "Array Microphone");
    expect(h.ready).toHaveBeenCalledOnce();
    expect(h.problems).toEqual([]);
  });

  it("stamps face events in server time and sends them to Rust", async () => {
    const h = harness();
    await h.services.start(async () => tracks());
    const options = h.faceOptions();
    if (!options) throw new Error("the face module wasn't started");

    options.onEvent(event());

    expect(h.enqueue).toHaveBeenCalledWith(event());
    const iso = options.toServerIso(1000);
    expect(iso).toBe(new Date(performance.timeOrigin + 1000 + 1500).toISOString());
  });

  it("starts nothing in the webview when Rust started nothing (the stub)", async () => {
    const h = harness({ ...ALL_UP, proctoring: false, recording: false, monitoring: false });
    const getTracks = vi.fn(async () => tracks());

    await h.services.start(getTracks);

    expect(getTracks).not.toHaveBeenCalled();
    expect(h.deps.startRecording).not.toHaveBeenCalled();
    expect(h.deps.startFace).not.toHaveBeenCalled();
  });

  it("asks again for a part that failed, and starts it when it comes up", async () => {
    const h = harness([
      {
        ...ALL_UP,
        proctoring: false,
        monitoring: false,
        policy: null,
        problems: [{ part: "proctoring", code: "network" }],
      },
      ALL_UP,
    ]);

    await h.services.start(async () => tracks());
    expect(h.deps.startFace).not.toHaveBeenCalled();
    expect(h.deps.startRecording).toHaveBeenCalledOnce();
    expect(h.problems).toEqual(["proctoring"]);
    expect(h.scheduled).toHaveLength(1);

    h.scheduled[0]?.();
    await vi.waitFor(() => expect(h.deps.startFace).toHaveBeenCalledOnce());
    // Recording was already running and isn't started twice.
    expect(h.deps.startRecording).toHaveBeenCalledOnce();
    expect(h.ready).toHaveBeenCalledOnce();
  });

  it("gives up retrying after a few attempts", async () => {
    const failing: ServicesStarted = {
      ...ALL_UP,
      proctoring: false,
      recording: false,
      policy: null,
      problems: [{ part: "recording", code: "recording-unavailable" }],
    };
    const h = harness(failing);
    await h.services.start(async () => tracks());
    for (let attempt = 0; attempt < 10; attempt += 1) {
      h.scheduled.shift()?.();
      await vi.waitFor(() => undefined);
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    // One start, then five retries.
    expect(vi.mocked(h.deps.servicesStart).mock.calls.length).toBe(6);
  });

  it("stops in order: face, its last events, recording, then Rust", async () => {
    const h = harness();
    await h.services.start(async () => tracks());
    h.log.length = 0;

    await h.services.stop();

    expect(h.log).toEqual(["face.stop", "enqueue", "recording.stop", "services.stop"]);
  });

  it("still stops Rust when the recording or the call to Rust fails", async () => {
    const h = harness();
    await h.services.start(async () => tracks());
    vi.mocked(h.recording.stop).mockRejectedValueOnce(new Error("encoder"));
    vi.mocked(h.deps.servicesStop).mockRejectedValueOnce(new Error("gone"));

    await expect(h.services.stop()).resolves.toBeUndefined();
    expect(h.deps.servicesStop).toHaveBeenCalledOnce();
  });

  it("stops a track the server won't take", async () => {
    const h = harness();
    await h.services.start(async () => tracks());

    h.handlers.get(EVENTS.trackRefused)?.("camera");
    h.handlers.get(EVENTS.trackRefused)?.("screen-1");
    h.handlers.get(EVENTS.trackRefused)?.(42);

    expect(h.recording.stopTrack).toHaveBeenCalledTimes(1);
    expect(h.recording.stopTrack).toHaveBeenCalledWith("camera");
  });

  it("stops the media when Rust says the services are stopping", async () => {
    const h = harness();
    await h.services.start(async () => tracks());
    h.log.length = 0;

    h.handlers.get(EVENTS.stopMedia)?.(null);
    await vi.waitFor(() => expect(h.log).toContain("recording.stop"));
    expect(h.log).toEqual(["face.stop", "enqueue", "recording.stop"]);
  });

  it("lets go of the webview's part without stopping Rust when the screen goes away", async () => {
    const h = harness();
    await h.services.start(async () => tracks());

    h.services.dispose();
    await vi.waitFor(() => expect(h.recording.stop).toHaveBeenCalled());

    expect(h.deps.servicesStop).not.toHaveBeenCalled();
    expect(h.handlers.size).toBe(0);
  });

  it("stops the camera and microphone it opened itself, and only those", async () => {
    const own = harness();
    const ownTracks = tracks({ owned: true });
    await own.services.start(async () => ownTracks);
    await own.services.stop();
    expect(ownTracks.camera?.stop).toHaveBeenCalled();
    expect(ownTracks.mic?.stop).toHaveBeenCalled();

    const shared = harness();
    const sharedTracks = tracks({ owned: false });
    await shared.services.start(async () => sharedTracks);
    await shared.services.stop();
    expect(sharedTracks.camera?.stop).not.toHaveBeenCalled();
  });

  it("keeps going when Rust can't be reached at first", async () => {
    const h = harness();
    vi.mocked(h.deps.servicesStart).mockRejectedValueOnce({ code: "network" });

    await h.services.start(async () => tracks());

    expect(h.problems).toEqual(["proctoring"]);
    expect(h.scheduled).toHaveLength(1);
  });
});

describe("time and device helpers", () => {
  it("shifts the browser clock to the server's", () => {
    const iso = serverIso(-250)(0);
    expect(iso).toBe(new Date(performance.timeOrigin - 250).toISOString());
  });

  it("names only a live device", () => {
    expect(liveLabel(track("camera"))).toBe("Integrated Camera");
    expect(liveLabel(track("camera", "ended"))).toBeNull();
    expect(liveLabel(null)).toBeNull();
  });
});
