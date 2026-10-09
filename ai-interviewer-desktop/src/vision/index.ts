// The on-device face module (SP-15a). SP-08b starts it during the interview:
//
//   const face = await startFaceModule({
//     source: videoFrameSource(video),
//     config: visionConfigFromPolicy(proctorSession),
//     toServerIso,                       // server-time clock from the session's clock sync
//     onEvent: (event) => forward(event), // to the native queue, which assigns `seq`
//     onStats: (stats) => { heartbeat.vision_fps = stats.fps; },
//   });
//   face.stop(); // on a break or at the end: ends open episodes, then stops the worker

export {
  ACCOMMODATIONS,
  applyAccommodations,
  DEFAULT_VISION_CONFIG,
  type SignalRule,
  type VisionConfig,
  type VisionPolicy,
  visionConfigFromPolicy,
} from "./config";
export { localClock, type ServerClock, SignalEngine, toCameraEvent } from "./engine";
export {
  type FaceModule,
  type FaceModuleOptions,
  type FrameSource,
  startFaceModule,
  type VisionStats,
  videoFrameSource,
} from "./face-module";
export { DEFAULT_FRAME_RATE, type FrameRateConfig } from "./frame-rate";
export type { Delegate } from "./protocol";
export {
  CAMERA_SIGNALS,
  type CameraEvent,
  type CameraSignal,
  type FaceObservation,
  type ProctoringEvent,
  type ProctoringEventDraft,
} from "./types";
