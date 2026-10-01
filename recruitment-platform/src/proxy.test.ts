import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEV_ROLE_COOKIE } from "./auth/session";
import { proxy } from "./proxy";

// Like Next, the request URL carries the server's own fallback host; the Host header is the one
// the browser asked for.
function request(
  path: string,
  host: string,
  role?: string,
  extra: Record<string, string> = {},
): NextRequest {
  return new NextRequest(`http://localhost:3000${path}`, {
    headers: {
      host,
      ...(role ? { cookie: `${DEV_ROLE_COOKIE}=${role}` } : {}),
      ...extra,
    },
  });
}

beforeEach(() => {
  vi.stubEnv("HV_WEB_DEV_TOOLS", "true");
  // No API in unit tests: an anonymous request must not wait for one.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 404 })),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("proxy", () => {
  it("serves each host its own route tree", async () => {
    const response = await proxy(request("/jobs", "app.hirevion.localhost", "recruiter"));
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "http://localhost:3000/recruiter/jobs",
    );
    const portal = await proxy(request("/download", "candidate.hirevion.localhost"));
    expect(portal.headers.get("x-middleware-rewrite")).toBe(
      "http://localhost:3000/portal/download",
    );
  });

  it("refuses hosts it doesn't serve", async () => {
    expect((await proxy(request("/jobs", "evil.example"))).status).toBe(421);
  });

  it("sends anonymous visitors to sign in, remembering where they were going", async () => {
    const response = await proxy(request("/jobs?status=open", "app.hirevion.localhost:3100"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.origin).toBe("http://app.hirevion.localhost:3100");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/jobs?status=open");
  });

  it("keeps https when the gateway says the browser used it", async () => {
    const response = await proxy(
      request("/jobs", "app.hirevion.localhost", undefined, { "x-forwarded-proto": "https" }),
    );
    expect(new URL(response.headers.get("location") ?? "").origin).toBe(
      "https://app.hirevion.localhost",
    );
  });

  it("guards a percent-encoded path the same as the plain one", async () => {
    const response = await proxy(request("/%6Aobs", "app.hirevion.localhost"));
    expect(response.status).toBe(307);
  });

  it("answers 403 with the forbidden page when the session lacks the permission", async () => {
    const response = await proxy(request("/admin/users", "app.hirevion.localhost", "recruiter"));
    expect(response.status).toBe(403);
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      "http://localhost:3000/recruiter/forbidden",
    );
  });

  it("never guards the public pages", async () => {
    const login = await proxy(request("/login", "app.hirevion.localhost"));
    expect(login.headers.get("x-middleware-rewrite")).toBe("http://localhost:3000/recruiter/login");
    expect(login.status).toBe(200);
  });

  it("tells the pages which path was asked for", async () => {
    const response = await proxy(
      request("/jobs?status=open", "app.hirevion.localhost", "recruiter"),
    );
    expect(response.headers.get("x-middleware-request-x-hv-path")).toBe("/jobs?status=open");
  });

  it("sets the CSP and security headers on every page", async () => {
    const response = await proxy(request("/dashboard", "app.hirevion.localhost", "recruiter"));
    expect(response.headers.get("content-security-policy")).toMatch(/'nonce-[^']+'/);
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  });
});
