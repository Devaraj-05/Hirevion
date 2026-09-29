import createClient, { type Client, type Middleware } from "openapi-fetch";
import { problemFromResponse } from "./problem";
import type { paths } from "./schema";

export type ApiClient = Client<paths>;

export interface ApiClientOptions {
  /** Origin of the API, e.g. `https://app.hirevion.localhost` (the web app's own host). */
  baseUrl: string;
  /** A replacement for `fetch` (tests, or the desktop's Rust bridge). */
  fetch?: (request: Request) => Promise<Response>;
}

/** Every non-2xx response is thrown as an `ApiProblem`, so callers only handle `data`. */
const throwProblems: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw await problemFromResponse(response);
    return response;
  },
};

/** A typed client for the Hirevion API, generated from its OpenAPI document. */
export function createApiClient(options: ApiClientOptions): ApiClient {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  client.use(throwProblems);
  return client;
}

/**
 * A key for one logical create. Send it as `Idempotency-Key`, and send the same key again
 * when retrying that create, so it takes effect once.
 */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
