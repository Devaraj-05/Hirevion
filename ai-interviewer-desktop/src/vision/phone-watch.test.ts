import { describe, expect, it } from "vitest";
import type { FrameSource } from "./face-module";
import type { FromObjectWorker, ToObjectWorker } from "./object-worker";
import { type ObjectWorkerLike, PHONE_LABELS, PhoneWatch } from "./phone-watch";

class FakeWorker implements ObjectWorkerLike {
  posted: ToObjectWorker[] = [];
  terminated = false;
  onmessage: ((event: MessageEvent<FromObjectWorker>) => void) | null = null;

  postMessage(message: ToObjectWorker): void {
    this.posted.push(message);
  }

  terminate(): void {
    this.terminated = true;
  }

  answer(message: FromObjectWorker): void {
    this.onmessage?.({ data: message } as MessageEvent<FromObjectWorker>);
  }
}

const bitmap = () => ({ close() {} }) as unknown as ImageBitmap;
const source: FrameSource = { grab: async () => bitmap() };

function setup() {
  let now = 0;
  const worker = new FakeWorker();
  const watch = new PhoneWatch(source, worker, () => now);
  return { watch, worker, at: (ms: number) => (now = ms) };
}

const detections = (...found: Array<[string, number]>): FromObjectWorker => ({
  type: "detections",
  detections: found.map(([label, score]) => ({
    label,
    score,
    box: { x: 0, y: 0, width: 10, height: 10 },
  })),
  width: 640,
  height: 360,
});

describe("PhoneWatch", () => {
  it("asks the object worker for phones only", async () => {
    const { watch, worker } = setup();
    await watch.look();
    expect(worker.posted).toHaveLength(1);
    expect(worker.posted[0]?.labels).toEqual(PHONE_LABELS);
  });

  it("keeps the best phone score while it is fresh", async () => {
    const { watch, worker, at } = setup();
    await watch.look();
    worker.answer(detections(["cell phone", 0.4], ["cell phone", 0.72], ["person", 0.9]));
    expect(watch.score()).toBe(0.72);
    at(1_400);
    expect(watch.score()).toBe(0.72);
    at(1_600);
    expect(watch.score()).toBeNull();
  });

  it("reads no phone as zero, a claim that none is there", async () => {
    const { watch, worker } = setup();
    await watch.look();
    worker.answer(detections(["person", 0.9]));
    expect(watch.score()).toBe(0);
  });

  it("doesn't pile up looks while the worker is busy", async () => {
    const { watch, worker, at } = setup();
    await watch.look();
    at(1_000);
    await watch.look();
    expect(worker.posted).toHaveLength(1);
    at(3_100);
    await watch.look();
    expect(worker.posted).toHaveLength(2);
  });

  it("stops the worker", () => {
    const { watch, worker } = setup();
    watch.stop();
    expect(worker.terminated).toBe(true);
  });
});
