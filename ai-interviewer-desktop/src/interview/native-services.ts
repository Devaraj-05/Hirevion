import { listen } from "@tauri-apps/api/event";
import type { Room } from "livekit-client";
import { Track } from "livekit-client";
import { commands, SERVICES_EVENTS } from "../native/commands";
import { recordingCommands } from "../recording/native";
import { startMediaRecording } from "../recording/recorder";
import { startFaceModule, videoFrameSource, visionConfigFromPolicy } from "../vision";
import type {
  FaceHandle,
  FaceStartOptions,
  LocalTracks,
  ServicesDeps,
  ServicesOptions,
} from "./services";

/** The real thing: Rust's commands, the recorder and the face module. */
export const nativeDeps: ServicesDeps = {
  servicesStart: commands.servicesStart,
  servicesStop: commands.servicesStop,
  setDevices: commands.proctoringSetDevices,
  enqueue: commands.proctoringEnqueue,
  clockOffsetMs: async () => (await recordingCommands.clock()).server_offset_ms,
  startRecording: startMediaRecording,
  startFace: startFaceOnTrack,
  visionConfig: (policy) => visionConfigFromPolicy(policy ?? {}),
  listen: async (event, handler) => listen(event, (message) => handler(message.payload)),
  schedule: (run, ms) => {
    const timer = window.setTimeout(run, ms);
    return () => window.clearTimeout(timer);
  },
};

export const nativeOptions: Pick<ServicesOptions, "events"> = {
  events: { trackRefused: SERVICES_EVENTS.trackRefused, stopMedia: SERVICES_EVENTS.stopMedia },
};

/** The face module reads frames from a `<video>`; this one is invisible and plays the camera. */
async function startFaceOnTrack(
  camera: MediaStreamTrack,
  options: FaceStartOptions,
): Promise<FaceHandle> {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = new MediaStream([camera]);
  Object.assign(video.style, {
    position: "fixed",
    width: "1px",
    height: "1px",
    opacity: "0",
    pointerEvents: "none",
  });
  video.setAttribute("aria-hidden", "true");
  document.body.append(video);
  const remove = () => {
    video.srcObject = null;
    video.remove();
  };
  try {
    await video.play();
    const face = await startFaceModule({ ...options, source: videoFrameSource(video) });
    return {
      stop: () => {
        face.stop();
        remove();
      },
    };
  } catch (error) {
    remove();
    throw error;
  }
}

/** The camera and microphone LiveKit publishes: the same tracks the interviewer sees. */
export function livekitTracks(room: Room): LocalTracks {
  const media = (source: Track.Source) =>
    room.localParticipant.getTrackPublication(source)?.track?.mediaStreamTrack ?? null;
  return {
    camera: media(Track.Source.Camera),
    mic: media(Track.Source.Microphone),
    owned: false,
  };
}

/** Text mode has no room, so the app opens the camera and microphone itself. */
export async function openLocalTracks(): Promise<LocalTracks> {
  const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  return {
    camera: stream.getVideoTracks()[0] ?? null,
    mic: stream.getAudioTracks()[0] ?? null,
    owned: true,
  };
}
