"use client";

import {
  type ApiClient,
  type components,
  createApiClient,
  isApiProblem,
  newIdempotencyKey,
} from "@hirevion/api-client";
import { readCookie } from "@/data/cookies";

/**
 * The portal's calls from the browser (ADR-0022). They go to `/api/v1/portal/*` on the portal's
 * own host, and repeat the candidate's CSRF cookie, never the recruiter's.
 */

export const PORTAL_CSRF_COOKIE = "__Host-hv_candidate_csrf";

export type RequestKind = components["schemas"]["PortalRequestCreate"]["kind"];
export type PortalRequestCreate = components["schemas"]["PortalRequestCreate"];

let client: ApiClient | undefined;

export function portalClient(): ApiClient {
  client ??= createApiClient({
    baseUrl: window.location.origin,
    csrfToken: () => readCookie(PORTAL_CSRF_COOKIE),
  });
  return client;
}

export type SignInResult =
  | { ok: true }
  | { ok: false; reason: "invalid" | "unavailable" }
  | { ok: false; reason: "locked"; retryAfter: number | null };

export async function portalSignIn(email: string, password: string): Promise<SignInResult> {
  try {
    await portalClient().POST("/api/v1/portal/auth/login", { body: { email, password } });
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

/** Ends the portal session. Failures are ignored: the browser signs out regardless. */
export async function portalSignOut(): Promise<void> {
  try {
    await portalClient().POST("/api/v1/portal/auth/logout");
  } catch {
    // Already signed out, or the API is unreachable.
  }
}

export async function portalForgotPassword(
  email: string,
): Promise<"sent" | "limited" | "unavailable"> {
  try {
    await portalClient().POST("/api/v1/portal/auth/password/forgot", { body: { email } });
    return "sent";
  } catch (error) {
    return isApiProblem(error) && error.status === 429 ? "limited" : "unavailable";
  }
}

export type PasswordResult =
  | { ok: true }
  | { ok: false; reason: "expired" | "unavailable" }
  | { ok: false; reason: "rejected"; codes: string[] };

/** From an emailed link: the invitation's first password (`set`) or a reset. */
export async function portalSetPassword(
  mode: "set" | "reset",
  token: string,
  password: string,
): Promise<PasswordResult> {
  try {
    const path =
      mode === "set" ? "/api/v1/portal/auth/password/set" : "/api/v1/portal/auth/password/reset";
    await portalClient().POST(path, { body: { token, password } });
    return { ok: true };
  } catch (error) {
    if (isApiProblem(error) && error.code === "invalid-token") {
      return { ok: false, reason: "expired" };
    }
    if (isApiProblem(error) && error.code === "password-rejected") {
      return { ok: false, reason: "rejected", codes: error.errors.map((item) => item.detail) };
    }
    return { ok: false, reason: "unavailable" };
  }
}

export type RequestResult =
  | { ok: true; reference: string }
  | { ok: false; reason: "invalid"; problem: string }
  | { ok: false; reason: "limited" | "unavailable" };

export async function createPortalRequest(body: PortalRequestCreate): Promise<RequestResult> {
  try {
    const { data } = await portalClient().POST("/api/v1/portal/requests", {
      body,
      headers: { "Idempotency-Key": newIdempotencyKey() },
    });
    return { ok: true, reference: data?.reference ?? "" };
  } catch (error) {
    if (isApiProblem(error) && error.status === 429) return { ok: false, reason: "limited" };
    if (isApiProblem(error) && error.status >= 400 && error.status < 500) {
      return { ok: false, reason: "invalid", problem: error.title };
    }
    return { ok: false, reason: "unavailable" };
  }
}
