"use client";

import { type ApiClient, createApiClient } from "@hirevion/api-client";

let client: ApiClient | undefined;

/**
 * The API, called on this app's own origin: the gateway sends /api/* to the backend, so there's
 * no CORS and the session cookie goes with every call.
 */
export function apiClient(): ApiClient {
  client ??= createApiClient({ baseUrl: window.location.origin });
  return client;
}
