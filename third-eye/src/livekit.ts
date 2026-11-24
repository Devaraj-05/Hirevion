import {
  LocalVideoTrack,
  Room,
  RoomEvent,
  Track,
  type TrackPublishOptions,
  VideoPresets,
} from "livekit-client";
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

/**
 * How the phone sends its camera: 720p at 1.2 Mbps for the recorder and the vision agent, plus a
 * 180p simulcast layer the candidate's laptop shows in its side camera tile (C8-12).
 */
export const CAMERA_PUBLISH: TrackPublishOptions = {
  source: Track.Source.Camera,
  simulcast: true,
  videoSimulcastLayers: [VideoPresets.h180],
  videoEncoding: { maxBitrate: 1_200_000, maxFramerate: 15 },
};

class LiveRoom implements RoomLike {
  constructor(readonly room: Room) {}

  get connected(): boolean {
    return this.room.state === "connected";
  }

  async publishCamera(camera: CameraTrack): Promise<void> {
    await this.room.localParticipant.publishTrack((camera as LiveCamera).track, CAMERA_PUBLISH);
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
