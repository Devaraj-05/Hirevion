import { type components, isApiProblem } from "@hirevion/api-client";
import { apiClient } from "@/data/api";
import { fieldErrors } from "@/data/problems";

/**
 * The browser's calls to `/api/v1/auth/*`, each answering what its form needs to show. The API
 * never says whether an account exists, so neither do these results.
 */

export type SignInResult =
  | { ok: true }
  | { ok: false; reason: "invalid" }
  | { ok: false; reason: "locked"; retryAfter: number | null }
  | { ok: false; reason: "unavailable" };

export type PasswordResult =
  | { ok: true }
  | { ok: false; reason: "expired" }
  | { ok: false; reason: "rejected"; problems: Record<string, string> }
  | { ok: false; reason: "unavailable" };

export type EmailChangeResult =
  | { ok: true }
  | { ok: false; reason: "rejected"; problems: Record<string, string> }
  | { ok: false; reason: "unavailable" };

export type SessionItem = components["schemas"]["SessionItem"];

export async function signIn(email: string, password: string): Promise<SignInResult> {
  try {
    await apiClient().POST("/api/v1/auth/login", { body: { email, password } });
    return { ok: true };
  } catch (error) {
    if (isApiProblem(error) && error.status === 401) return { ok: false, reason: "invalid" };
    if (isApiProblem(error) && error.status === 429) {
      const retry = error.raw.retry_after;
      return { ok: false, reason: "locked", retryAfter: typeof retry === "number" ? retry : null };
    }
    return { ok: false, reason: "unavailable" };
  }
}

/** Ends the API session. Failures are ignored: the browser signs out regardless. */
export async function signOutOfApi(): Promise<void> {
  try {
    await apiClient().POST("/api/v1/auth/logout");
  } catch {
    // Already signed out, or the API is unreachable; the cookies go either way.
  }
}

export async function requestPasswordReset(
  email: string,
): Promise<"sent" | "limited" | "unavailable"> {
  try {
    await apiClient().POST("/api/v1/auth/password/forgot", { body: { email } });
    return "sent";
  } catch (error) {
    return isApiProblem(error) && error.status === 429 ? "limited" : "unavailable";
  }
}

function passwordFailure(error: unknown): PasswordResult {
  if (isApiProblem(error) && error.code === "invalid-token")
    return { ok: false, reason: "expired" };
  if (isApiProblem(error) && error.code === "password-rejected") {
    return { ok: false, reason: "rejected", problems: fieldErrors(error) };
  }
  return { ok: false, reason: "unavailable" };
}

/** From an emailed link: a reset of a forgotten password, or an invited user's first one. */
export async function setNewPassword(
  mode: "reset" | "set",
  token: string,
  password: string,
): Promise<PasswordResult> {
  try {
    if (mode === "reset") {
      await apiClient().POST("/api/v1/auth/password/reset", { body: { token, password } });
    } else {
      await apiClient().POST("/api/v1/auth/password/set", { body: { token, password } });
    }
    return { ok: true };
  } catch (error) {
    return passwordFailure(error);
  }
}

export async function changePassword(current: string, next: string): Promise<PasswordResult> {
  try {
    await apiClient().POST("/api/v1/auth/password/change", {
      body: { current_password: current, new_password: next },
    });
    return { ok: true };
  } catch (error) {
    return passwordFailure(error);
  }
}

export async function changeEmail(newEmail: string, password: string): Promise<EmailChangeResult> {
  try {
    await apiClient().POST("/api/v1/auth/email/change", {
      body: { new_email: newEmail, password },
    });
    return { ok: true };
  } catch (error) {
    if (isApiProblem(error) && error.code === "password-rejected") {
      return { ok: false, reason: "rejected", problems: fieldErrors(error) };
    }
    return { ok: false, reason: "unavailable" };
  }
}

export async function verifyEmail(token: string): Promise<"verified" | "expired" | "unavailable"> {
  try {
    await apiClient().POST("/api/v1/auth/email/verify", { body: { token } });
    return "verified";
  } catch (error) {
    return isApiProblem(error) && error.code === "invalid-token" ? "expired" : "unavailable";
  }
}

export async function listSessions(): Promise<SessionItem[]> {
  const { data } = await apiClient().GET("/api/v1/auth/sessions");
  return data ?? [];
}

export async function revokeSession(id: string): Promise<void> {
  await apiClient().DELETE("/api/v1/auth/sessions/{session_id}", {
    params: { path: { session_id: id } },
  });
}

export async function revokeOtherSessions(): Promise<void> {
  await apiClient().POST("/api/v1/auth/sessions/revoke-others");
}
