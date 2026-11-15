import type { VideoCaptureOptions } from "livekit-client";

/** Which of the phone's cameras films: the rear one (the default) or the front one. */
export type Facing = "environment" | "user";

/** The product owner's decision (2026-11-15): a button flips between the two cameras. */
export function nextFacing(facing: Facing): Facing {
  return facing === "environment" ? "user" : "environment";
}

/** What `LocalVideoTrack.restartTrack` needs to film with `facing` at 720p and 15 fps. The
 * published track stays the same, so the interview's recording keeps going. */
export function captureOptions(facing: Facing): VideoCaptureOptions {
  return { facingMode: facing, resolution: { width: 1280, height: 720, frameRate: 15 } };
}
