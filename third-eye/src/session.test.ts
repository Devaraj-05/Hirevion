import { describe, expect, it } from "vitest";
import { PairingError } from "./api";
import {
  type CameraTrack,
  type EyeDeps,
  EyeSession,
  type EyeState,
  type RoomLike,
} from "./session";

class FakeRoom implements RoomLike {
  connected = true;
  published: CameraTrack | null = null;
  private onDrop: (() => void) | null = null;
  async publishCamera(track: CameraTrack) {
    this.published = track;
  }
  async unpublishCamera() {
    this.published = null;
  }
  async disconnect() {
    this.connected = false;
  }
  onDisconnected(handler: () => void) {
    this.onDrop = handler;
  }
  drop() {
    this.connected = false;
    this.onDrop?.();
  }
}

function harness(overrides: Partial<EyeDeps> = {}) {
  const log: string[] = [];
  const rooms: FakeRoom[] = [];
  const cameras: { stopped: boolean }[] = [];
  const deps: EyeDeps = {
    openCamera: async () => {
      const camera = { stopped: false, stop: () => (camera.stopped = true) };
      cameras.push(camera);
      return camera;
    },
    connect: async (url, token) => {
      log.push(`connect ${url} ${token}`);
      const room = new FakeRoom();
      rooms.push(room);
      return room;
    },
    rejoin: async () => {
      log.push("rejoin");
      return { url: "wss://eye", token: `t${log.length}` };
    },
    holdWakeLock: async () => void log.push("wake"),
    releaseWakeLock: async () => void log.push("sleep"),
    wait: async () => undefined,
    ...overrides,
  };
  const states: EyeState[] = [];
  const session = new EyeSession(deps, { url: "wss://eye", token: "t0" }, (s) => states.push(s));
  return { session, deps, log, rooms, cameras, states };
}

describe("EyeSession", () => {
  it("opens the camera, joins, publishes and keeps the screen on", async () => {
    const { session, log, rooms, states } = harness();
    await session.start();
    expect(log).toEqual(["connect wss://eye t0", "wake"]);
    expect(rooms[0]?.published).not.toBeNull();
    expect(states.at(-1)).toBe("live");
  });

  it("unpublishes as soon as the page is hidden (a lock), and resumes when visible", async () => {
    const { session, rooms, cameras, states, log } = harness();
    await session.start();
    await session.hidden();
    expect(rooms[0]?.published).toBeNull();
    expect(cameras[0]?.stopped).toBe(true);
    expect(states.at(-1)).toBe("paused");
    expect(log.at(-1)).toBe("sleep");
    await session.visible();
    expect(rooms[0]?.published).not.toBeNull();
    expect(cameras).toHaveLength(2);
    expect(states.at(-1)).toBe("live");
  });

  it("rejoins with a fresh token when the room dropped while hidden", async () => {
    const { session, rooms, log, states } = harness();
    await session.start();
    await session.hidden();
    rooms[0]?.drop();
    await session.visible();
    expect(log).toContain("rejoin");
    expect(rooms).toHaveLength(2);
    expect(rooms[1]?.published).not.toBeNull();
    expect(states.at(-1)).toBe("live");
  });

  it("reconnects by itself after a drop, backing off between attempts", async () => {
    const waits: number[] = [];
    let failures = 2;
    const { session, rooms, states } = harness({
      wait: async (ms) => void waits.push(ms),
      rejoin: async () => {
        if (failures-- > 0) throw new Error("offline");
        return { url: "wss://eye", token: "fresh" };
      },
    });
    await session.start();
    rooms[0]?.drop();
    await session.settled();
    expect(states).toContain("reconnecting");
    expect(states.at(-1)).toBe("live");
    expect(waits).toEqual([1_000, 2_000, 4_000]);
    expect(rooms).toHaveLength(2);
  });

  it("stops for good when the pairing was revoked", async () => {
    const { session, rooms, states } = harness({
      rejoin: async () => {
        throw new PairingError("pairing-revoked", "This pairing was cancelled.", true);
      },
    });
    await session.start();
    rooms[0]?.drop();
    await session.settled();
    expect(states.at(-1)).toBe("ended");
  });

  it("reports a camera that can't open", async () => {
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    const { session, states } = harness({
      openCamera: async () => {
        throw denied;
      },
    });
    await expect(session.start()).rejects.toBe(denied);
    expect(states.at(-1)).toBe("failed");
  });

  it("lets the camera go when joining fails, so retries don't pile up open cameras", async () => {
    let connects = 0;
    const base = harness();
    const { session, cameras } = harness({
      connect: async (url, token) => {
        connects += 1;
        if (connects === 2 || connects === 3) throw new Error("offline");
        return base.deps.connect(url, token);
      },
    });
    await session.start();
    base.rooms.at(-1)?.drop();
    await session.settled();
    expect(cameras).toHaveLength(4);
    expect(cameras.slice(0, -1).every((c) => c.stopped)).toBe(true);
    expect(cameras.at(-1)?.stopped).toBe(false);
  });

  it("stays paused when the phone locks while a reconnection is under way", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let first = true;
    const { session, rooms, states } = harness({
      rejoin: async () => {
        if (first) {
          first = false;
          await gate;
        }
        return { url: "wss://eye", token: "fresh" };
      },
    });
    await session.start();
    rooms[0]?.drop();
    await Promise.resolve();
    await session.hidden();
    release();
    await session.settled();
    expect(states.at(-1)).toBe("paused");
    expect(rooms.at(-1)?.published).toBeNull();
    await session.visible();
    expect(states.at(-1)).toBe("live");
    expect(rooms.at(-1)?.published).not.toBeNull();
  });
});
