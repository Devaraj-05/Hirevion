import type { VoiceState } from "../native/commands";

/** The interview's voice connection, as the screen shows it. */
export type Connection = "connecting" | "connected" | "reconnecting" | "off";

/**
 * What the interviewer's orb shows (C8-12): the interviewer speaking (blue, moving with its
 * voice), listening (a still halo), the candidate speaking (violet, moving with the microphone),
 * thinking (a slow shimmer), connecting, voice off, or resting (waiting, paused, ended).
 */
export type OrbState =
  | "speaking"
  | "listening"
  | "candidate"
  | "thinking"
  | "connecting"
  | "reconnecting"
  | "off"
  | "resting";

export function orbState(
  voice: VoiceState,
  connection: Connection,
  candidateSpeaking: boolean,
): OrbState {
  if (connection === "off") return "off";
  if (connection === "reconnecting") return "reconnecting";
  if (connection !== "connected") return "connecting";
  if (voice === "speaking") return "speaking";
  if (voice === "thinking") return "thinking";
  if (voice === "listening") return candidateSpeaking ? "candidate" : "listening";
  return "resting";
}
