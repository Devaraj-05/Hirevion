import type { InterviewState, VoiceState } from "../native/commands";

/** The LiveKit data topics the agent and the desktop share (contract interview-session). */
export const STATE_TOPIC = "hv.state";
export const CONTROL_TOPIC = "hv.control";
export type ControlAction = "done_answering" | "repeat" | "need_a_moment";

const VOICE_STATES: readonly VoiceState[] = [
  "listening",
  "thinking",
  "speaking",
  "waiting",
  "paused",
  "ended",
  "error",
];

/** The fields an `hv.state` message updates; null when the message isn't one. Unknown or
 * malformed fields are left out, so a bad message never breaks the screen. */
export function parseStateMessage(data: Uint8Array): Partial<InterviewState> | null {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder().decode(data));
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const message = value as Record<string, unknown>;
  const patch: Partial<InterviewState> = {};
  if (VOICE_STATES.includes(message.voice as VoiceState)) patch.voice = message.voice as VoiceState;
  if ("question" in message) {
    const question = message.question;
    if (question === null) patch.question = null;
    else if (
      typeof question === "object" &&
      typeof (question as { id?: unknown }).id === "string"
    ) {
      patch.question = question as InterviewState["question"];
    }
  }
  if (typeof message.remaining_seconds === "number")
    patch.remaining_seconds = message.remaining_seconds;
  if ("notice" in message) patch.notice = (message.notice as InterviewState["notice"]) ?? null;
  if (typeof message.message === "string") patch.message = message.message;
  return patch;
}

export function mergeState(state: InterviewState, patch: Partial<InterviewState>): InterviewState {
  return { ...state, ...patch };
}

export function controlMessage(action: ControlAction): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(JSON.stringify({ action }));
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}
