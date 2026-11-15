import { describe, expect, it } from "vitest";
import type { FromObjectWorker, ToObjectWorker } from "../vision/object-worker";
import { type DetectorWorker, FAIL_AFTER, PlacementDetector } from "./detector";

class FakeWorker implements DetectorWorker {
  sent: ToObjectWorker[] = [];
  onmessage: ((event: MessageEvent<FromObjectWorker>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  terminated = false;
  postMessage(message: ToObjectWorker): void {
    this.sent.push(message);
  }
  answer(data: FromObjectWorker): void {
    this.onmessage?.({ data } as MessageEvent<FromObjectWorker>);
  }
  terminate(): void {
    this.terminated = true;
  }
}

const frames = { grab: async () => ({ width: 640, height: 360, close() {} }) as ImageBitmap };
const seen: FromObjectWorker = { type: "detections", detections: [], width: 640, height: 360 };

describe("the placement detector", () => {
  it("returns what the worker saw in a frame", async () => {
    const worker = new FakeWorker();
    const detector = new PlacementDetector(worker, () => 0);
    const pending = detector.detect(frames);
    await Promise.resolve();
    worker.answer(seen);
    expect(await pending).toMatchObject({ width: 640, height: 360 });
  });

  it("checks one frame at a time", async () => {
    const worker = new FakeWorker();
    const detector = new PlacementDetector(worker, () => 0);
    void detector.detect(frames);
    await Promise.resolve();
    expect(await detector.detect(frames)).toBeNull();
    expect(worker.sent).toHaveLength(1);
  });

  it("gives up on a worker that doesn't answer, and fails after it keeps not answering", async () => {
    const worker = new FakeWorker();
    let now = 0;
    const detector = new PlacementDetector(worker, () => now);
    for (let tries = 0; tries < FAIL_AFTER; tries += 1) {
      void detector.detect(frames);
      await Promise.resolve();
      now += 2_500; // longer than the 2 s it waits for an answer
    }
    expect(await detector.detect(frames)).toBeNull();
    expect(detector.failed).toBe(true);
  });

  it("fails at once when the model can't start", async () => {
    const worker = new FakeWorker();
    const detector = new PlacementDetector(worker, () => 0);
    const pending = detector.detect(frames);
    await Promise.resolve();
    worker.answer({ type: "error", message: "no WebAssembly", fatal: true });
    expect(await pending).toBeNull();
    expect(detector.failed).toBe(true);
  });
});
