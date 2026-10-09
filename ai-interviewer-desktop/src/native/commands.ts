import { invoke } from "@tauri-apps/api/core";
import type { CheckResult } from "../checks/types";

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
  return typeof value === "object" && value !== null && typeof (value as CommandError).code === "string";
}

export const commands = {
  appInfo: () => invoke<AppInfo>("app_info"),
  releaseCheck: () => invoke<ReleaseState>("release_check"),
  signIn: (email: string, password: string) => invoke<SignInResult>("sign_in", { email, password }),
  verifyCode: (challengeId: string, code: string) =>
    invoke<SignInResult>("verify_code", { challengeId, code }),
  resendCode: (challengeId: string) => invoke<null>("resend_code", { challengeId }),
  signOut: () => invoke<null>("sign_out"),
  profile: () => invoke<Profile>("profile"),
  nativeChecks: () => invoke<CheckResult[]>("native_checks"),
  screenCaptureProbe: () => invoke<CheckResult>("screen_capture_probe"),
  apiRoundTrip: () => invoke<{ rtt_ms: number }>("api_round_trip"),
  submitChecks: (interviewId: string, results: CheckResult[]) =>
    invoke<ChecksSubmitted>("submit_checks", { interviewId, results }),
};
