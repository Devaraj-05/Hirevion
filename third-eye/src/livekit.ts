import { LocalVideoTrack, Room, RoomEvent, Track } from "livekit-client";
import type { CameraTrack, Credentials, EyeDeps, RoomLike } from "./session";

/** The browser's side of `EyeDeps`: the rear camera at 720p/15 fps, LiveKit, Wake Lock. */

interface LiveCamera extends CameraTrack {
  track: LocalVideoTrack;
}

export const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: {
    facingMode: { ideal: "environment" },
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 15, max: 15 },
  },
};

async function openCamera(): Promise<LiveCamera> {
  const stream = await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
  const camera = stream.getVideoTracks()[0];
  if (!camera) {
    throw new Error("The camera returned no video.");
  }
  const track = new LocalVideoTrack(camera);
  return { track, stop: () => track.stop() };
}

class LiveRoom implements RoomLike {
  constructor(readonly room: Room) {}

  get connected(): boolean {
    return this.room.state === "connected";
  }

  async publishCamera(camera: CameraTrack): Promise<void> {
    await this.room.localParticipant.publishTrack((camera as LiveCamera).track, {
      source: Track.Source.Camera,
      simulcast: false,
      videoEncoding: { maxBitrate: 1_200_000, maxFramerate: 15 },
    });
  }

  async unpublishCamera(): Promise<void> {
    for (const publication of this.room.localParticipant.videoTrackPublications.values()) {
      if (publication.track) {
        await this.room.localParticipant.unpublishTrack(publication.track, true);
      }
    }
  }

  async disconnect(): Promise<void> {
    await this.room.disconnect();
  }

  onDisconnected(handler: () => void): void {
    this.room.on(RoomEvent.Disconnected, handler);
  }
}

let wakeLock: WakeLockSentinel | null = null;

export function browserDeps(
  rejoin: () => Promise<Credentials>,
  onCamera: (camera: LocalVideoTrack) => void,
): EyeDeps {
  return {
    openCamera: async () => {
      const camera = await openCamera();
      onCamera(camera.track);
      return camera;
    },
    connect: async (url, token) => {
      const room = new Room({ adaptiveStream: false, dynacast: false });
      await room.connect(url, token, { autoSubscribe: false });
      return new LiveRoom(room);
    },
    rejoin,
    holdWakeLock: async () => {
      // Safari 16.4+ and Chrome: keeps the screen on while the camera runs.
      if (!("wakeLock" in navigator) || wakeLock) return;
      wakeLock = await navigator.wakeLock.request("screen").catch(() => null);
      wakeLock?.addEventListener("release", () => {
        wakeLock = null;
      });
    },
    releaseWakeLock: async () => {
      await wakeLock?.release().catch(() => undefined);
      wakeLock = null;
    },
    wait: (ms) => new Promise((resolve) => window.setTimeout(resolve, ms)),
  };
}
