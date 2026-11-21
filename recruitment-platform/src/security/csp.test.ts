import { describe, expect, it } from "vitest";
import { buildCsp, SECURITY_HEADERS } from "./csp";

function directives(csp: string): Map<string, string> {
  return new Map(
    csp.split(";").map((part) => {
      const [name = "", ...values] = part.trim().split(/\s+/);
      return [name, values.join(" ")];
    }),
  );
}

describe("buildCsp", () => {
  it("allows only this request's nonce'd scripts", () => {
    const csp = directives(buildCsp("abc123", false));
    expect(csp.get("script-src")).toBe("'self' 'nonce-abc123' 'strict-dynamic'");
    expect(csp.get("object-src")).toBe("'none'");
    expect(csp.get("base-uri")).toBe("'self'");
    expect(csp.get("frame-ancestors")).toBe("'none'");
    expect(csp.get("form-action")).toBe("'self'");
    expect(csp.get("default-src")).toBe("'self'");
    expect(csp.get("connect-src")).toBe("'self'");
  });

  it("permits eval only for the development server", () => {
    expect(directives(buildCsp("n", true)).get("script-src")).toContain("'unsafe-eval'");
    expect(directives(buildCsp("n", false)).get("script-src")).not.toContain("unsafe-eval");
  });

  it("allows inline styles, which Radix uses to position popovers", () => {
    expect(directives(buildCsp("n", false)).get("style-src")).toBe("'self' 'unsafe-inline'");
  });
});

describe("buildCsp's storage origin", () => {
  // Recordings and evidence pictures play from signed links to blob storage, another origin:
  // the review player's media and the analytics' pictures were blocked (C8-8, 2026-11-21).
  it("lets images and media load from the storage origin, and nothing else from it", () => {
    const csp = directives(buildCsp("n", false, "https://storage.hirevion.localhost"));
    expect(csp.get("img-src")).toBe("'self' data: blob: https://storage.hirevion.localhost");
    expect(csp.get("media-src")).toBe("'self' blob: https://storage.hirevion.localhost");
    expect(csp.get("connect-src")).toBe("'self'");
    expect(csp.get("default-src")).toBe("'self'");
  });

  it("keeps an origin only: no path, wildcard or other scheme", () => {
    expect(directives(buildCsp("n", false, "http://127.0.0.1:10000/hirevion")).get("img-src")).toBe(
      "'self' data: blob: http://127.0.0.1:10000",
    );
    for (const bad of [
      "*",
      "https://*.blob.core.windows.net",
      "javascript:alert(1)",
      "not a url",
      "",
    ]) {
      expect(directives(buildCsp("n", false, bad)).get("img-src")).toBe("'self' data: blob:");
    }
  });
});

describe("SECURITY_HEADERS", () => {
  it("sets the baseline headers", () => {
    expect(SECURITY_HEADERS).toMatchObject({
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "X-Content-Type-Options": "nosniff",
    });
    expect(SECURITY_HEADERS["Permissions-Policy"]).toContain("camera=()");
  });
});
