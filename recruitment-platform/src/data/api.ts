"use client";

import { type ApiClient, createApiClient } from "@hirevion/api-client";
import { readCookie } from "./cookies";

/** The CSRF cookie the API sets at sign-in; state-changing calls repeat it in a header. */
export const CSRF_COOKIE = "__Host-hv_csrf";

let client: ApiClient | undefined;

/**
 * The API, called on this app's own origin: the gateway sends /api/* to the backend, so there's
 * no CORS and the session cookie goes with every call.
 */
export function apiClient(): ApiClient {
  client ??= createApiClient({
    baseUrl: window.location.origin,
    csrfToken: () => readCookie(CSRF_COOKIE),
  });
  return client;
}
