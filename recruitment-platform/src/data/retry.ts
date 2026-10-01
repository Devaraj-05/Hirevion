import { isApiProblem } from "@hirevion/api-client";

const MAX_RETRIES = 2;

/** Retry what might succeed next time: server errors, rate limits and network failures. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (isApiProblem(error) && error.status < 500 && error.status !== 429) return false;
  return failureCount < MAX_RETRIES;
}
