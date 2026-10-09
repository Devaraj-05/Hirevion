import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type FaceModule, type FaceModuleOptions, startFaceModule } from "./face-module";
import type { FromWorker, ToWorker } from "./protocol";
import type { CameraEvent, FaceBox } from "./types";

const ONE: FaceBox[] = [{ x: 0.4, y: 0.3, width: 0.26, height: 0.35, score: 0.9 }];
const SCENE = { meanLuma: 0.45, stdLuma: 0.2, edgeEnergy: 0.08 };

/** Stands in for the MediaPipe worker: records messages; the test answers them. */
class FakeWorker {
  readonly sent: ToWorker[] = [];
  onmessage: ((event: MessageEvent<FromWorker>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  terminated = false;

  postMessage(message: ToWorker): void {
    this.sent.push(message);
  }

  terminate(): void {
    this.terminated = true;
  }

  reply(message: FromWorker): void {
    this.onmessage?.({ data: message } as MessageEvent<FromWorker>);
  }

  frames() {
    return this.sent.filter((message) => message.type === "frame");
  }

  /** Answers the latest frame as the worker would. */
  answer(faces: FaceBox[], processingMs = 10): void {
    const frame = this.frames().at(-1);
    if (frame?.type !== "frame") throw new Error("no frame to answer");
    this.reply({
      type: "result",
      t: frame.t,
      faces,
      frame: SCENE,
      inferenceMs: processingMs - 1,
      processingMs,
    });
  }
}

/** A frame source whose bitmaps are plain objects: no camera is opened. */
function fakeSource() {
  let grabbed = 0;
  const closed: number[] = [];
  return {
    get grabbed() {
      return grabbed;
    },
    closed,
    async grab() {
      grabbed += 1;
      const id = grabbed;
      return { close: () => closed.push(id), width: 640, height: 360 } as unknown as ImageBitmap;
    },
  };
}

let worker: FakeWorker;

async function start(options: Partial<FaceModuleOptions> = {}) {
  worker = new FakeWorker();
  const starting = startFaceModule({
    source: fakeSource(),
    createWorker: () => worker,
    now: () => Date.now(),
    ...options,
  });
  worker.reply({ type: "ready", delegate: "GPU" });
  return starting;
}

/** Runs the loop for `ms`, answering every frame the moment it is sent. */
async function runAnswering(ms: number, faces: FaceBox[], processingMs = 10) {
  for (let elapsed = 0; elapsed < ms; elapsed += 10) {
    const before = worker.frames().length;
    await vi.advanceTimersByTimeAsync(10);
    if (worker.frames().length > before) worker.answer(faces, processingMs);
  }
}

describe("the face module", () => {
  let module: FaceModule | null = null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
  });

  afterEach(() => {
    module?.stop();
    module = null;
    vi.useRealTimers();
  });

  it("asks the worker for the GPU delegate and reports the one it got", async () => {
    worker = new FakeWorker();
    const starting = startFaceModule({ source: fakeSource(), createWorker: () => worker });
    expect(worker.sent[0]).toMatchObject({ type: "init", delegate: "GPU", model: "face_detector" });
    worker.reply({ type: "ready", delegate: "CPU" });
    module = await starting;
    expect(module.stats().delegate).toBe("CPU");
  });

  it("fails to start when the worker can't load MediaPipe", async () => {
    worker = new FakeWorker();
    const starting = startFaceModule({ source: fakeSource(), createWorker: () => worker });
    worker.reply({ type: "error", message: "no WebAssembly", fatal: true });
    await expect(starting).rejects.toThrow("no WebAssembly");
    expect(worker.terminated).toBe(true);
  });

  it("sends a frame every 100 ms at 10 fps and skips while the worker is busy", async () => {
    module = await start();
    await vi.advanceTimersByTimeAsync(350);
    expect(worker.frames()).toHaveLength(1);
    expect(module.stats().framesSkipped).toBe(2);
    worker.answer(ONE);
    await vi.advanceTimersByTimeAsync(100);
    expect(worker.frames()).toHaveLength(2);
  });

  it("turns the worker's results into proctoring events", async () => {
    const events: CameraEvent[] = [];
    module = await start({ onEvent: (event) => events.push(event) });
    await runAnswering(6_000, []);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "FACE_ABSENT",
      source: "camera",
      confidence: 1,
      details: { phase: "started", level: "warning" },
    });
    expect(events[0]?.duration_ms).toBeGreaterThan(5_000);
    expect(module.active()).toEqual(["FACE_ABSENT"]);
  });

  it("passes every observation on, with the frame's time", async () => {
    const seen: number[] = [];
    module = await start({ onObservation: (observation) => seen.push(observation.faces.length) });
    await runAnswering(1_000, ONE);
    expect(seen.length).toBeGreaterThanOrEqual(9);
    expect(seen.every((faces) => faces === 1)).toBe(true);
  });

  it("lowers the frame rate when the worker takes too long", async () => {
    module = await start();
    await runAnswering(2_000, ONE, 40);
    expect(module.stats().targetFps).toBe(5);
    const before = worker.frames().length;
    await runAnswering(1_000, ONE, 40);
    expect(worker.frames().length - before).toBe(5);
  });

  it("reports its stats every second", async () => {
    const fps: number[] = [];
    module = await start({ onStats: (stats) => fps.push(stats.fps) });
    await runAnswering(3_000, ONE);
    expect(fps).toHaveLength(3);
    expect(fps.at(-1)).toBeGreaterThanOrEqual(9);
    expect(module.stats().inferenceMs?.p50).toBe(9);
  });

  it("frees a frame the worker never answers", async () => {
    const errors: string[] = [];
    module = await start({ onError: (message) => errors.push(message) });
    await vi.advanceTimersByTimeAsync(2_500);
    expect(worker.frames().length).toBeGreaterThan(1);
    expect(errors.some((message) => message.includes("didn't answer"))).toBe(true);
  });

  it("ends open episodes, stops sending and terminates the worker on stop", async () => {
    const events: CameraEvent[] = [];
    module = await start({ onEvent: (event) => events.push(event) });
    await runAnswering(6_000, []);
    module.stop();
    module = null;
    expect(events.map((event) => event.details.phase)).toEqual(["started", "ended"]);
    expect(worker.terminated).toBe(true);
    const sent = worker.frames().length;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(worker.frames()).toHaveLength(sent);
  });
});
