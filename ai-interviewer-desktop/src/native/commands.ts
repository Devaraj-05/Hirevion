import { Channel, invoke } from "@tauri-apps/api/core";
import type { SystemCheckPayload } from "../checks/payload";
import type { CheckResult } from "../checks/types";
import type { ProctoringEventDraft } from "../vision/types";

/**
 * The Rust side of the app (`src-tauri/src/app`). The webview never holds a token or calls the
 * API itself: every call goes through these commands, which return only what the screens show
 * (master plan §6.4). A failed command rejects with a `CommandError`.
 */

export interface CommandError {
  code: string;
  detail?: string | null;
  /** Extra fields from the API's problem (e.g. `minimum_version`, `attempts_left`). */
  extra?: Record<string, unknown>;
}

export interface AppInfo {
  version: string;
  channel: string;
  arch: string;
  os: string;
  debug: boolean;
}

export interface ReleaseState {
  status: "ok" | "update-available" | "update-required";
  latest_version?: string | null;
  minimum_version?: string | null;
  download_url?: string | null;
}

/** What the update download reports (`src-tauri/src/app/update.rs`). */
export type UpdateProgress =
  | { event: "downloading"; downloaded: number; total: number | null }
  | { event: "installing" };

export interface UpdateOutcome {
  /** `installed` is only seen where the installer returns; on Windows the app restarts. */
  status: "up-to-date" | "installed";
  version: string | null;
}

export interface Candidate {
  id: string;
  name: string;
  email: string;
  locale: string;
}

export interface Organization {
  id: string;
  name: string;
  support_email: string | null;
}

export interface InterviewSummary {
  id: string;
  job_title: string;
  status: string;
  starts_at: string;
  expires_at: string;
  duration_minutes: number;
  third_eye: "off" | "optional" | "required";
  proctoring_level: string;
  coding: boolean;
}

export interface Profile {
  candidate: Candidate;
  organization: Organization;
  interviews: InterviewSummary[];
}

export type SignInResult =
  | ({ status: "ok" } & Profile)
  | { status: "code_required"; challenge_id: string; sent_to: string };

export interface ChecksSubmitted {
  id: string;
  passed: boolean;
  failed_mandatory: string[];
}

export function isCommandError(value: unknown): value is CommandError {
  return (
    typeof value === "object" && value !== null && typeof (value as CommandError).code === "string"
  );
}

export const commands = {
  appInfo: () => invoke<AppInfo>("app_info"),
  releaseCheck: () => invoke<ReleaseState>("release_check"),
  /**
   * Checks for a newer signed release, downloads it (reporting progress), verifies it against
   * the key built into the app and installs it. Windows restarts the app when it succeeds.
   */
  updateInstall: (onProgress: (progress: UpdateProgress) => void) => {
    const channel = new Channel<UpdateProgress>();
    channel.onmessage = onProgress;
    return invoke<UpdateOutcome>("update_install", { onProgress: channel });
  },
  /** Sends a webview error to crash reporting (a no-op unless this build has a GlitchTip DSN). */
  crashReport: (error: { kind: string; message: string; stack: string | null }) =>
    invoke<null>("crash_report", { error }),
  signIn: (email: string, password: string) => invoke<SignInResult>("sign_in", { email, password }),
  verifyCode: (challengeId: string, code: string) =>
    invoke<SignInResult>("verify_code", { challengeId, code }),
  resendCode: (challengeId: string) => invoke<null>("resend_code", { challengeId }),
  signOut: () => invoke<null>("sign_out"),
  profile: () => invoke<Profile>("profile"),
  nativeChecks: () => invoke<CheckResult[]>("native_checks"),
  screenCaptureProbe: () => invoke<CheckResult>("screen_capture_probe"),
  apiRoundTrip: () => invoke<{ rtt_ms: number }>("api_round_trip"),
  submitChecks: (interviewId: string, payload: SystemCheckPayload) =>
    interviewRequest<ChecksSubmitted>(interviewId, "system_checks", payload),
  briefing: (interviewId: string) => interviewRequest<Briefing>(interviewId, "briefing"),
  consents: (interviewId: string, body: ConsentBody) =>
    interviewRequest<ConsentResult>(interviewId, "consents", body),
  requestAccommodations: (interviewId: string, kinds: AccommodationKind[], note: string) =>
    interviewRequest<{ id: string; status: string }>(interviewId, "accommodations", {
      kinds,
      note,
    }),
  start: (interviewId: string, systemCheckId: string, consentId: string) =>
    interviewRequest<StartResult>(interviewId, "start", {
      system_check_id: systemCheckId,
      consent_id: consentId,
    }),
  session: (interviewId: string) =>
    interviewRequest<{ state: InterviewState }>(interviewId, "session"),
  answer: (interviewId: string, questionId: string, text: string) =>
    interviewRequest<{ state: InterviewState }>(interviewId, "answer", {
      question_id: questionId,
      text,
    }),
  complete: (interviewId: string, reason: "finished" | "candidate_ended") =>
    interviewRequest<{ status: string }>(interviewId, "complete", { reason }),
  /** Starts the proctor session, the native monitor and recording; safe to call again. */
  servicesStart: (interviewId: string) =>
    invoke<ServicesStarted>("services_start", { interviewId }),
  /** Ends monitoring and screen recording; the rest of the recording uploads in the background. */
  servicesStop: () => invoke<null>("services_stop"),
  /** The camera and microphone in use, by label; `null` for one that isn't capturing. */
  proctoringSetDevices: (camera: string | null, mic: string | null) =>
    invoke<null>("proctoring_set_devices", { camera, mic }),
  /** A camera event from the face module; Rust numbers it and sends it with the others. */
  proctoringEnqueue: (event: ProctoringEventDraft) => invoke<null>("proctoring_enqueue", { event }),
  uploadProgress: (interviewId: string) =>
    invoke<UploadProgress>("upload_progress", { interviewId }),
};

/** What `services_start` reports: which parts run, and which didn't start (try again). */
export interface ServicesStarted {
  proctoring: boolean;
  monitoring: boolean;
  recording: boolean;
  screen: boolean;
  /** The proctor policy's `thresholds` and `accommodations`, for the camera analysis. */
  policy: { thresholds?: Record<string, unknown>; accommodations?: string[] } | null;
  problems: { part: "proctoring" | "recording"; code: string }[];
}

/** How much of the recording the server has acknowledged (the upload-drain screen). */
export interface UploadProgress {
  pending: number;
  pending_bytes: number;
  acknowledged: number;
  /** Segments whose file is gone: the server sees a gap. */
  lost: number;
  /** Segments the server refused for good. */
  rejected: number;
  /** 0 to 100; 100 only when `done`. */
  percent: number;
  /** Recording hasn't stopped, so more segments will follow. */
  recording: boolean;
  /** Nothing left to upload and nothing more to record: closing the app is safe. */
  done: boolean;
}

/** Events Rust sends the webview while the services run. */
export const SERVICES_EVENTS = {
  /** The server won't take a camera or microphone track (payload: the track name). */
  trackRefused: "hv:track-refused",
  /** The services are stopping: stop recording the camera and microphone. */
  stopMedia: "hv:stop-media",
} as const;

/** The interview calls (contract interview-session), made by Rust with the session token. */
export type InterviewAction =
  | "briefing"
  | "system_checks"
  | "consents"
  | "accommodations"
  | "start"
  | "session"
  | "answer"
  | "workspace"
  | "complete";

function interviewRequest<T>(interviewId: string, action: InterviewAction, body?: unknown) {
  return invoke<T>("interview_request", { interviewId, action, body: body ?? null });
}

export const CONSENT_PURPOSES = [
  "camera",
  "microphone",
  "screen",
  "audio",
  "video",
  "third_eye",
  "transcript",
  "coding_activity",
  "system_telemetry",
  "proctoring_events",
] as const;
export type ConsentPurpose = (typeof CONSENT_PURPOSES)[number];

export const ACCOMMODATION_KINDS = [
  "extended_time",
  "text_answers",
  "breaks",
  "assistive_technology",
  "relaxed_gaze",
  "third_eye_waiver",
] as const;
export type AccommodationKind = (typeof ACCOMMODATION_KINDS)[number];

export interface Briefing {
  instructions: string[];
  mandatory_checks: string[];
  notice: {
    version: string;
    items: { purpose: ConsentPurpose; text: string; required: boolean }[];
  };
  accommodations: { requested: string[]; approved: string[] };
  answer_mode: "voice" | "text";
  third_eye: "off" | "optional" | "required";
}

export interface ConsentBody {
  notice_version: string;
  items: { purpose: ConsentPurpose; accepted: boolean }[];
}

export interface ConsentResult {
  id: string;
  complete: boolean;
  missing: string[];
}

export interface Question {
  id: string;
  index: number;
  text: string;
  type: string;
  time_limit_seconds: number | null;
  workspace: "none" | "code" | "whiteboard";
  languages: string[];
}

export type VoiceState =
  | "listening"
  | "thinking"
  | "speaking"
  | "waiting"
  | "paused"
  | "ended"
  | "error";

export interface InterviewState {
  status: string;
  remaining_seconds: number;
  answer_mode: "voice" | "text";
  question: Question | null;
  voice: VoiceState;
  stage: string;
  message: string | null;
  notice: { kind: string } | null;
  third_eye?: string;
  workspace?: string;
}

export interface StartResult {
  livekit_url: string | null;
  room: string;
  participant_identity?: string;
  participant_token?: string;
  token_expires_at?: string;
  state: InterviewState;
}
