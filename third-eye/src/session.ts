import { PairingError } from "./api";

/**
 * The phone's streaming loop, free of the browser and LiveKit so it can be tested:
 *
 * - **start:** open the rear camera, join the room, publish, keep the screen on (Wake Lock);
 * - **hidden** (the phone locked, or the candidate switched apps): unpublish at once, so the
 *   server's LiveKit webhook flags the third eye within seconds, and let the camera go;
 * - **visible:** publish again, rejoining with a fresh token if the room dropped meanwhile;
 * - **dropped** while visible: reconnect by itself, backing off, until the pairing is revoked.
 */

export interface CameraTrack {
  stop(): void;
}

export interface RoomLike {
  readonly connected: boolean;
  publishCamera(track: CameraTrack): Promise<void>;
  unpublishCamera(): Promise<void>;
  disconnect(): Promise<void>;
  onDisconnected(handler: () => void): void;
}

export interface Credentials {
  url: string;
  token: string;
}

export interface EyeDeps {
  openCamera(): Promise<CameraTrack>;
  connect(url: string, token: string): Promise<RoomLike>;
  /** A fresh token for this pairing (the device secret, `POST /third-eye/rejoin`). */
  rejoin(): Promise<Credentials>;
  holdWakeLock(): Promise<void>;
  releaseWakeLock(): Promise<void>;
  wait(ms: number): Promise<void>;
}

export type EyeState =
  | "idle"
  | "starting"
  | "live"
  | "paused"
  | "reconnecting"
  | "failed"
  | "ended";

const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 15_000];
const MAX_ATTEMPTS = 40;

export class EyeSession {
  private room: RoomLike | null = null;
  private camera: CameraTrack | null = null;
  private state: EyeState = "idle";
  private pending: Promise<void> = Promise.resolve();
  private stopping = false;

  constructor(
    private readonly deps: EyeDeps,
    private readonly first: Credentials,
    private readonly onState: (state: EyeState) => void,
  ) {}

  get current(): EyeState {
    return this.state;
  }

  private set(state: EyeState) {
    this.state = state;
    this.onState(state);
  }

  /** Resolves once any reconnection in progress has finished. */
  settled(): Promise<void> {
    return this.pending;
  }

  async start(): Promise<void> {
    this.set("starting");
    try {
      await this.join(this.first);
    } catch (error) {
      this.set("failed");
      throw error;
    }
    await this.deps.holdWakeLock();
    this.set("live");
  }

  async hidden(): Promise<void> {
    if (this.state !== "live" && this.state !== "reconnecting") return;
    this.set("paused");
    const room = this.room;
    if (room?.connected) {
      await room.unpublishCamera().catch(() => undefined);
    }
    this.camera?.stop();
    this.camera = null;
    await this.deps.releaseWakeLock();
  }

  async visible(): Promise<void> {
    if (this.state !== "paused") return;
    try {
      if (this.room?.connected) {
        await this.publish(this.room);
      } else {
        await this.join(await this.deps.rejoin());
      }
    } catch (error) {
      if (error instanceof PairingError && error.final) {
        this.set("ended");
        return;
      }
      this.pending = this.reconnect();
      return;
    }
    await this.deps.holdWakeLock();
    this.set("live");
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.camera?.stop();
    this.camera = null;
    await this.room?.disconnect();
    await this.deps.releaseWakeLock();
    this.set("ended");
  }

  private async publish(room: RoomLike): Promise<void> {
    const camera = await this.deps.openCamera();
    this.camera = camera;
    await room.publishCamera(camera);
  }

  private async join(credentials: Credentials): Promise<void> {
    const camera = await this.deps.openCamera();
    this.camera = camera;
    const room = await this.deps.connect(credentials.url, credentials.token);
    this.room = room;
    room.onDisconnected(() => this.dropped(room));
    await room.publishCamera(camera);
  }

  private dropped(room: RoomLike) {
    // A room this session replaced, its own goodbye, or a lock (`visible` rejoins): nothing to do.
    if (room !== this.room || this.stopping || this.state === "paused") return;
    if (this.state === "ended" || this.state === "reconnecting") return;
    this.camera?.stop();
    this.camera = null;
    this.pending = this.reconnect();
  }

  private async reconnect(): Promise<void> {
    this.set("reconnecting");
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      await this.deps.wait(BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 15_000);
      if (this.stopping || this.state !== "reconnecting") return;
      try {
        await this.join(await this.deps.rejoin());
      } catch (error) {
        if (error instanceof PairingError && error.final) {
          this.set("ended");
          return;
        }
        continue;
      }
      await this.deps.holdWakeLock();
      this.set("live");
      return;
    }
    this.set("failed");
  }
}
