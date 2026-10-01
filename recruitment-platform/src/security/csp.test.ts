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

describe("SECURITY_HEADERS", () => {
  it("sets the baseline headers", () => {
    expect(SECURITY_HEADERS).toMatchObject({
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "X-Content-Type-Options": "nosniff",
    });
    expect(SECURITY_HEADERS["Permissions-Policy"]).toContain("camera=()");
  });
});
