import type { ServicesStarted } from "../native/commands";
import type { WebviewTrack } from "../recording/formats";
import type { MediaRecording, RecordingOptions } from "../recording/recorder";
import type { VisionConfig } from "../vision/config";
import type { CameraEvent, ProctoringEventDraft } from "../vision/types";

/** The camera and microphone the interview uses. */
export interface LocalTracks {
  camera: MediaStreamTrack | null;
  mic: MediaStreamTrack | null;
  /** The app opened them itself (text mode), so it stops them at the end. */
  owned: boolean;
}

export interface FaceHandle {
  stop(): void;
}

export interface FaceStartOptions {
  config: VisionConfig;
  toServerIso: (monotonicMs: number) => string;
  onEvent: (event: CameraEvent) => void;
  onError: (message: string) => void;
}

/** What the controller needs from the outside, so a test can stand in for all of it. */
export interface ServicesDeps {
  servicesStart(interviewId: string): Promise<ServicesStarted>;
  servicesStop(): Promise<unknown>;
  setDevices(camera: string | null, mic: string | null): Promise<unknown>;
  enqueue(event: ProctoringEventDraft): Promise<unknown>;
  /** Server time minus this PC's time, in milliseconds. */
  clockOffsetMs(): Promise<number>;
  startRecording(stream: MediaStream, options: RecordingOptions): Promise<MediaRecording>;
  startFace(camera: MediaStreamTrack, options: FaceStartOptions): Promise<FaceHandle>;
  visionConfig(policy: ServicesStarted["policy"]): VisionConfig;
  /** Subscribes to a Rust event; resolves to the unsubscribe function. */
  listen(event: string, handler: (payload: unknown) => void): Promise<() => void>;
  /** Runs `run` after `ms`; returns the cancel function. */
  schedule(run: () => void, ms: number): () => void;
}

export interface ServicesOptions {
  /** Retry delay for parts that failed to start. */
  retryMs?: number;
  maxRetries?: number;
  /** A part that couldn't start or has stopped for good. */
  onProblem?: (part: "recording" | "vision" | "proctoring") => void;
  /** Every part started (a retry may have fixed what `onProblem` reported). */
  onReady?: () => void;
  events: { trackRefused: string; stopMedia: string };
}

/** Browser time to the server's: `started_at` is in server time (`proctoring.md`). */
export function serverIso(offsetMs: number): (monotonicMs: number) => string {
  return (monotonicMs) => new Date(performance.timeOrigin + monotonicMs + offsetMs).toISOString();
}

/** A track's label while it captures; `null` once it has ended or is missing. */
export function liveLabel(track: MediaStreamTrack | null): string | null {
  return track && track.readyState === "live" ? track.label : null;
}

const WEBVIEW_TRACKS: readonly string[] = ["camera", "mic"];

/**
 * The webview's part of the interview services (SP-08b): it asks Rust to start them, then
 * feeds them. The face module's events go to Rust's proctoring queue, the camera and
 * microphone go to the recorder, and the devices in use are reported for the disconnect rules.
 * Ending it stops the face module first (its open episodes become events), waits for those
 * events to reach Rust, then stops the recording, then tells Rust to stop.
 */
export class InterviewServices {
  private tracks: LocalTracks | null = null;
  private recording: MediaRecording | null = null;
  private face: FaceHandle | null = null;
  private readonly pending = new Set<Promise<unknown>>();
  private readonly unlisten: (() => void)[] = [];
  private cancelRetry: (() => void) | null = null;
  private attempts = 0;
  private failed = false;
  private reported = false;
  private disposed = false;
  private listening = false;
  private chain: Promise<unknown> = Promise.resolve();

  constructor(
    private readonly interviewId: string,
    private readonly deps: ServicesDeps,
    private readonly options: ServicesOptions,
  ) {}

  /**
   * Starts the services and the webview's part once `getTracks` has the media (called when
   * needed). Safe to call again: it only fills in what is missing.
   */
  start(getTracks: () => Promise<LocalTracks>): Promise<void> {
    return this.enqueueTask(() => this.ensure(getTracks));
  }

  /** The interview is over: ends everything, last events and segments first. Never rejects. */
  async stop(): Promise<void> {
    this.disposed = true;
    this.cancelPendingRetry();
    await this.enqueueTask(async () => {
      await this.stopWebview();
      try {
        await this.deps.servicesStop();
      } catch {
        // The server notices the missing heartbeats and flags a telemetry gap by itself.
      }
      this.release();
    });
  }

  /** The screen went away without the interview ending: let go of the webview's part. */
  dispose(): void {
    this.disposed = true;
    this.cancelPendingRetry();
    void this.enqueueTask(async () => {
      await this.stopWebview();
      this.release();
    });
  }

  private enqueueTask(task: () => Promise<void>): Promise<void> {
    const next = this.chain.then(task);
    this.chain = next.catch(() => undefined);
    return next.catch(() => undefined);
  }

  private async ensure(getTracks: () => Promise<LocalTracks>): Promise<void> {
    if (this.disposed) return;
    this.failed = false;
    let started: ServicesStarted;
    try {
      started = await this.deps.servicesStart(this.interviewId);
    } catch {
      this.problem("proctoring");
      this.retryLater(getTracks);
      return;
    }
    if (this.disposed) return;
    await this.listen();
    if (started.recording || started.proctoring) {
      try {
        this.tracks ??= await getTracks();
      } catch {
        this.problem("recording");
      }
    }
    const tracks = this.tracks;
    if (tracks) {
      if (started.recording && !this.recording) await this.startRecording(tracks);
      if (started.proctoring && !this.face && tracks.camera) {
        await this.startFace(tracks.camera, started);
      }
      if (started.proctoring) this.reportDevices(tracks);
    }
    const rustProblem = started.problems[0];
    if (rustProblem) this.problem(rustProblem.part);
    if (this.failed) {
      this.retryLater(getTracks);
    } else {
      this.options.onReady?.();
    }
  }

  private problem(part: "recording" | "vision" | "proctoring"): void {
    this.failed = true;
    this.options.onProblem?.(part);
  }

  private async startRecording(tracks: LocalTracks): Promise<void> {
    const live = [tracks.camera, tracks.mic].filter(
      (track): track is MediaStreamTrack => track !== null && track.readyState === "live",
    );
    if (live.length === 0) return;
    try {
      this.recording = await this.deps.startRecording(new MediaStream(live), {
        onError: () => this.problem("recording"),
      });
    } catch {
      this.problem("recording");
    }
  }

  private async startFace(camera: MediaStreamTrack, started: ServicesStarted): Promise<void> {
    try {
      const offset = await this.deps.clockOffsetMs();
      this.face = await this.deps.startFace(camera, {
        config: this.deps.visionConfig(started.policy),
        toServerIso: serverIso(offset),
        onEvent: (event) => this.forward(event),
        onError: () => this.problem("vision"),
      });
    } catch {
      this.problem("vision");
    }
  }

  /** Face events go to Rust's queue; stopping waits for the ones still on their way. */
  private forward(event: CameraEvent): void {
    const sent = this.deps.enqueue(event).catch(() => undefined);
    this.pending.add(sent);
    void sent.finally(() => this.pending.delete(sent));
  }

  private reportDevices(tracks: LocalTracks): void {
    if (this.reported) return;
    this.reported = true;
    const report = () => {
      void this.deps
        .setDevices(liveLabel(tracks.camera), liveLabel(tracks.mic))
        .catch(() => undefined);
    };
    report();
    for (const track of [tracks.camera, tracks.mic]) {
      // An unplugged device ends its track; the disconnect rules need to know.
      track?.addEventListener("ended", report, { once: true });
    }
  }

  private async listen(): Promise<void> {
    if (this.listening) return;
    this.listening = true;
    try {
      this.unlisten.push(
        await this.deps.listen(this.options.events.trackRefused, (track) => {
          if (typeof track === "string" && WEBVIEW_TRACKS.includes(track)) {
            void this.recording?.stopTrack(track as WebviewTrack).catch(() => undefined);
          }
        }),
        await this.deps.listen(this.options.events.stopMedia, () => {
          void this.enqueueTask(() => this.stopWebview());
        }),
      );
    } catch {
      // Without the events the interview still works; Rust refuses late segments.
    }
  }

  private retryLater(getTracks: () => Promise<LocalTracks>): void {
    const max = this.options.maxRetries ?? 5;
    if (this.disposed || this.attempts >= max) return;
    this.attempts += 1;
    this.cancelRetry = this.deps.schedule(() => {
      this.cancelRetry = null;
      void this.start(getTracks);
    }, this.options.retryMs ?? 10_000);
  }

  private cancelPendingRetry(): void {
    this.cancelRetry?.();
    this.cancelRetry = null;
  }

  private async stopWebview(): Promise<void> {
    const face = this.face;
    this.face = null;
    face?.stop();
    await Promise.allSettled([...this.pending]);
    const recording = this.recording;
    this.recording = null;
    try {
      await recording?.stop();
    } catch {
      this.problem("recording");
    }
  }

  private release(): void {
    for (const stop of this.unlisten.splice(0)) stop();
    const tracks = this.tracks;
    this.tracks = null;
    if (tracks?.owned) {
      for (const track of [tracks.camera, tracks.mic]) track?.stop();
    }
  }
}
