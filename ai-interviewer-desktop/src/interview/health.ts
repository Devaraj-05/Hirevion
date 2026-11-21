import type { LiveThirdEye } from "../third-eye/pairing";

/** How one part that protects the interview is doing. */
export type Health = "starting" | "ok" | "problem";

/** PRD §32's status strip: the camera, the microphone, the screen and the phone. */
export interface Indicators {
  camera: Health;
  microphone: Health;
  screen: Health;
  /** Null when the interview doesn't use a phone. */
  phone: Health | null;
}

/** The interview services' parts, as `InterviewServices` reports their problems. */
export type ServicePart = "recording" | "vision" | "proctoring";

/** PRD §32's status strip, from what the services and the phone's watcher report. */
export function indicators(
  problems: Set<ServicePart> | null,
  phone: LiveThirdEye | null,
): Indicators {
  const health = (...parts: ServicePart[]): Health =>
    parts.some((part) => problems?.has(part)) ? "problem" : problems ? "ok" : "starting";
  const watched = phone !== null && phone !== "not_required";
  return {
    camera: health("vision", "recording"),
    microphone: health("recording"),
    screen: health("proctoring", "recording"),
    phone: watched
      ? phone === "connected"
        ? "ok"
        : phone === "connecting"
          ? "starting"
          : "problem"
      : null,
  };
}
