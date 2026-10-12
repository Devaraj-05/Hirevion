import type { components } from "@hirevion/api-client";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { PATH_HEADER } from "@/auth/session";
import { portalLoginPath } from "./paths";

/**
 * The portal's server-side reads (ADR-0022). Pages fetch their data here, from the API, with the
 * candidate's own cookie only: the recruiter's cookie never leaves the browser for these calls.
 * A failed call is `null`, so a page shows "not available" instead of crashing.
 */

export const PORTAL_SESSION_COOKIE = "__Host-hv_candidate_session";

export type PortalSession = components["schemas"]["PortalSessionResponse"];
export type PortalInterviews = components["schemas"]["PortalInterviewList"];
export type PortalRequest = components["schemas"]["PortalRequestItem"];
export type Notices = components["schemas"]["NoticesResponse"];
export type Downloads = components["schemas"]["DownloadsResponse"];

const DEFAULT_API = "http://127.0.0.1:8000";
const TIMEOUT_MS = 3_000;

type Fetcher = typeof fetch;
type Env = Record<string, string | undefined>;

/** GET `path` on the API as the candidate (or anonymously): the body, or null on any failure. */
export async function portalGet<T>(
  path: string,
  session: string | undefined,
  env: Env = process.env,
  fetcher: Fetcher = fetch,
): Promise<T | null> {
  const requestHeaders: Record<string, string> = { accept: "application/json" };
  if (session) requestHeaders.cookie = `${PORTAL_SESSION_COOKIE}=${session}`;
  try {
    const response = await fetcher(`${env.HV_API_INTERNAL_URL ?? DEFAULT_API}/api/v1${path}`, {
      headers: requestHeaders,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

async function sessionCookie(): Promise<string | undefined> {
  return (await cookies()).get(PORTAL_SESSION_COOKIE)?.value;
}

/** The signed-in candidate, or null. */
export const getPortalSession = cache(async (): Promise<PortalSession | null> => {
  const token = await sessionCookie();
  return token ? portalGet<PortalSession>("/portal/auth/session", token) : null;
});

/** The signed-in candidate, or a redirect to sign in that comes back here. */
export async function requirePortalSession(): Promise<PortalSession> {
  const session = await getPortalSession();
  if (!session) redirect(portalLoginPath((await headers()).get(PATH_HEADER)));
  return session;
}

export async function getPortalInterviews(): Promise<PortalInterviews | null> {
  return portalGet<PortalInterviews>("/portal/interviews", await sessionCookie());
}

export async function getPortalRequests(): Promise<PortalRequest[] | null> {
  return portalGet<PortalRequest[]>("/portal/requests", await sessionCookie());
}

export async function getNotices(): Promise<Notices | null> {
  return portalGet<Notices>("/portal/notices", undefined);
}

export async function getDownloads(): Promise<Downloads | null> {
  return portalGet<Downloads>("/portal/downloads", undefined);
}
