import { ApiProblem } from "@hirevion/api-client";
import { describe, expect, it } from "vitest";
import { shouldRetry } from "./retry";

function problem(status: number): ApiProblem {
  return new ApiProblem({ type: "about:blank", title: "x", status, code: `http-${status}` });
}

describe("shouldRetry", () => {
  it("doesn't repeat a request the API refused", () => {
    expect(shouldRetry(0, problem(404))).toBe(false);
    expect(shouldRetry(0, problem(403))).toBe(false);
  });

  it("retries server and network failures twice", () => {
    expect(shouldRetry(0, problem(503))).toBe(true);
    expect(shouldRetry(1, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(2, problem(503))).toBe(false);
  });

  it("retries when rate-limited", () => {
    expect(shouldRetry(0, problem(429))).toBe(true);
  });
});
